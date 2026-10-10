import hashlib
import hmac
import os
import re
import uuid
from typing import Annotated
import base64
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import database, models, schemas
from app.auth import require_admin
from app.ota_service import (
    ACTIVE_STATES,
    OTA_ARTIFACT_DIR,
    OTA_SLOT_SIZE,
    artifact_path,
    assignment_response,
    clear_desired,
    hash_download_token,
    new_download_token,
    publish_desired,
    factory_artifact_path,
)


router = APIRouter(tags=["Firmware OTA"])
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_SIGNATURE_SIZE = 512
MAX_FACTORY_SIZE = 0x800000
OTA_SIGNING_PUBLIC_KEY_PATH = Path(
    os.getenv("OTA_SIGNING_PUBLIC_KEY_PATH", "/app/secrets/ota-signing-public.pem")
)


def _load_signing_key():
    try:
        key = serialization.load_pem_public_key(OTA_SIGNING_PUBLIC_KEY_PATH.read_bytes())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="OTA signing public key is unavailable") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise HTTPException(status_code=503, detail="OTA signing public key must use ECDSA P-256")
    public_der = key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, hashlib.sha256(public_der).hexdigest()[:16]


def _audit(
    db: Session,
    actor: models.User,
    action: str,
    entity_type: str,
    entity_id: int,
    reason: str | None = None,
) -> None:
    db.add(models.AuditLog(
        actor_user_id=actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        reason=reason,
    ))


def _read_signature(upload: UploadFile, label: str) -> bytes:
    value = upload.file.read(MAX_SIGNATURE_SIZE + 1)
    if not value or len(value) > MAX_SIGNATURE_SIZE:
        raise HTTPException(status_code=422, detail=f"{label} signature is invalid")
    return value


def _store_upload(upload: UploadFile, temp_path: Path, maximum_size: int, label: str) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with temp_path.open("xb") as output:
        while chunk := upload.file.read(UPLOAD_CHUNK_SIZE):
            size += len(chunk)
            if size >= maximum_size:
                raise HTTPException(status_code=413, detail=f"{label} is too large")
            digest.update(chunk)
            output.write(chunk)
    if size == 0:
        raise HTTPException(status_code=422, detail=f"{label} is empty")
    return size, digest.hexdigest()


def _verify_stored_artifact(path: Path, size: int, digest_hex: str, signature_base64: str | None,
                            public_key, label: str) -> None:
    if not path.is_file() or path.stat().st_size != size:
        raise HTTPException(status_code=409, detail=f"{label} is missing or has changed")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(UPLOAD_CHUNK_SIZE):
            digest.update(chunk)
    if not hmac.compare_digest(digest.hexdigest(), digest_hex):
        raise HTTPException(status_code=409, detail=f"{label} hash has changed")
    if not signature_base64:
        raise HTTPException(status_code=409, detail=f"{label} signature is missing")
    try:
        public_key.verify(
            base64.b64decode(signature_base64, validate=True),
            bytes.fromhex(digest_hex),
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
    except (InvalidSignature, ValueError):
        raise HTTPException(status_code=409, detail=f"{label} signature verification failed")


@router.post(
    "/admin/ota/releases",
    response_model=schemas.FirmwareReleaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_release(
    version: str = Form(...),
    release_notes: str | None = Form(None),
    artifact: UploadFile = File(...),
    signature: UploadFile = File(...),
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    factory_artifact: Annotated[UploadFile | None, File()] = None,
    factory_signature: Annotated[UploadFile | None, File()] = None,
    factory_only: Annotated[bool, Form()] = False,
):
    version = version.strip()
    if not SEMVER_RE.fullmatch(version):
        raise HTTPException(status_code=422, detail="Version must be valid SemVer")
    if release_notes and len(release_notes) > 5000:
        raise HTTPException(status_code=422, detail="Release notes are too long")
    if not artifact.filename or not artifact.filename.lower().endswith(".bin"):
        raise HTTPException(status_code=415, detail="Artifact must be a .bin file")
    if not signature.filename or not signature.filename.lower().endswith(".sig"):
        raise HTTPException(status_code=415, detail="Signature must be a .sig file")
    if (factory_artifact is None) != (factory_signature is None):
        raise HTTPException(status_code=422, detail="Factory artifact and signature must be uploaded together")
    if factory_artifact and (not factory_artifact.filename or not factory_artifact.filename.lower().endswith(".bin")):
        raise HTTPException(status_code=415, detail="Factory artifact must be a .bin file")
    if factory_signature and (not factory_signature.filename or not factory_signature.filename.lower().endswith(".sig")):
        raise HTTPException(status_code=415, detail="Factory signature must be a .sig file")
    if db.query(models.FirmwareRelease.id).filter(models.FirmwareRelease.version == version).first():
        raise HTTPException(status_code=409, detail="Firmware version already exists")

    OTA_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.bin"
    final_path = OTA_ARTIFACT_DIR / filename
    temp_path = OTA_ARTIFACT_DIR / f".{filename}.upload"
    factory_filename = f"{uuid.uuid4().hex}.factory.bin" if factory_artifact else None
    factory_final_path = OTA_ARTIFACT_DIR / factory_filename if factory_filename else None
    factory_temp_path = OTA_ARTIFACT_DIR / f".{factory_filename}.upload" if factory_filename else None
    try:
        signature_bytes = _read_signature(signature, "Firmware")
        factory_signature_bytes = _read_signature(factory_signature, "Factory") if factory_signature else None
        _, signing_key_id = _load_signing_key()
        size, digest_hex = _store_upload(artifact, temp_path, OTA_SLOT_SIZE, "Firmware artifact")
        os.replace(temp_path, final_path)
        factory_size = None
        factory_digest_hex = None
        if factory_artifact and factory_temp_path and factory_final_path:
            factory_size, factory_digest_hex = _store_upload(
                factory_artifact, factory_temp_path, MAX_FACTORY_SIZE + 1, "Factory artifact"
            )
            os.replace(factory_temp_path, factory_final_path)

        release = models.FirmwareRelease(
            version=version,
            status="draft",
            artifact_filename=filename,
            sha256=digest_hex,
            size_bytes=size,
            signature=base64.b64encode(signature_bytes).decode("ascii"),
            signing_key_id=signing_key_id,
            factory_artifact_filename=factory_filename,
            factory_sha256=factory_digest_hex,
            factory_size_bytes=factory_size,
            factory_signature=(base64.b64encode(factory_signature_bytes).decode("ascii")
                               if factory_signature_bytes else None),
            factory_only=factory_only,
            release_notes=release_notes,
            created_by=actor.id,
        )
        db.add(release)
        db.flush()
        _audit(db, actor, "ota.release.upload", "firmware_release", release.id)
        db.commit()
        db.refresh(release)
        return release
    except Exception:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        if factory_temp_path:
            factory_temp_path.unlink(missing_ok=True)
        if factory_final_path:
            factory_final_path.unlink(missing_ok=True)
        raise


@router.get("/admin/ota/releases", response_model=list[schemas.FirmwareReleaseResponse])
def list_releases(
    release_status: str | None = Query(None, alias="status", pattern="^(draft|ready|retired)$"),
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.FirmwareRelease)
    if release_status:
        query = query.filter(models.FirmwareRelease.status == release_status)
    return query.order_by(models.FirmwareRelease.created_at.desc()).all()


@router.post("/admin/ota/releases/{release_id}/publish", response_model=schemas.FirmwareReleaseResponse)
def publish_release(
    release_id: int,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    release = db.get(models.FirmwareRelease, release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Firmware release not found")
    if release.status == "retired":
        raise HTTPException(status_code=409, detail="Retired release cannot be published")
    public_key, signing_key_id = _load_signing_key()
    if release.signing_key_id != signing_key_id:
        raise HTTPException(status_code=409, detail="Firmware signing key does not match")
    _verify_stored_artifact(
        artifact_path(release), release.size_bytes, release.sha256, release.signature,
        public_key, "Firmware artifact",
    )
    if release.factory_artifact_filename:
        _verify_stored_artifact(
            factory_artifact_path(release), release.factory_size_bytes, release.factory_sha256,
            release.factory_signature, public_key, "Factory artifact",
        )
    release.status = "ready"
    _audit(db, actor, "ota.release.publish", "firmware_release", release.id)
    db.commit()
    db.refresh(release)
    return release


@router.get("/admin/ota/releases/{release_id}/factory-artifact")
def download_factory_artifact(
    release_id: int,
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    release = db.get(models.FirmwareRelease, release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Firmware release not found")
    if release.status != "ready" or not release.factory_artifact_filename:
        raise HTTPException(status_code=409, detail="Factory artifact is not ready")
    try:
        path = factory_artifact_path(release)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not path.is_file() or path.stat().st_size != release.factory_size_bytes:
        raise HTTPException(status_code=409, detail="Factory artifact is missing or has changed")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"aquanotes-{release.version}-factory.bin",
        headers={"X-Artifact-SHA256": release.factory_sha256},
    )


@router.post("/admin/ota/assignments", response_model=schemas.OtaAssignmentBatchResponse, status_code=201)
def create_assignments(
    payload: schemas.OtaAssignmentCreate,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    release = db.get(models.FirmwareRelease, payload.release_id)
    if not release or release.status != "ready":
        raise HTTPException(status_code=409, detail="Firmware release is not ready")
    if release.factory_only:
        raise HTTPException(status_code=409, detail="Factory-only release cannot be assigned over OTA")

    device_ids = list(dict.fromkeys(payload.device_ids))
    devices = db.query(models.Device).filter(models.Device.id.in_(device_ids)).all()
    if len(devices) != len(device_ids):
        raise HTTPException(status_code=404, detail="One or more devices were not found")

    tokens: dict[int, str] = {}
    assignments: list[models.DeviceOtaAssignment] = []
    now = datetime.utcnow()
    for device in devices:
        active = db.query(models.DeviceOtaAssignment).filter(
            models.DeviceOtaAssignment.device_id == device.id,
            models.DeviceOtaAssignment.state.in_(ACTIVE_STATES),
        ).all()
        for previous in active:
            previous.state = "cancelled"
            previous.completed_at = now
        if active:
            db.flush()

        token, token_hash = new_download_token()
        assignment = models.DeviceOtaAssignment(
            device=device,
            release=release,
            from_version=device.current_firmware_version,
            download_token_hash=token_hash,
            requested_by=actor.id,
            is_rollback=payload.rollback,
            mandatory=payload.mandatory,
        )
        db.add(assignment)
        db.flush()
        tokens[assignment.id] = token
        assignments.append(assignment)
        _audit(db, actor, "ota.assignment.create", "device_ota_assignment", assignment.id)

    db.commit()
    publish_failures = []
    for assignment in assignments:
        db.refresh(assignment)
        if not publish_desired(assignment, tokens[assignment.id]):
            publish_failures.append(assignment.id)
    return {
        "items": [assignment_response(item) for item in assignments],
        "publish_failures": publish_failures,
    }


@router.get("/admin/ota/assignments", response_model=list[schemas.OtaAssignmentResponse])
def list_assignments(
    assignment_state: str | None = Query(None, alias="state", max_length=30),
    device_id: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=500),
    _: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.DeviceOtaAssignment)
    if assignment_state:
        query = query.filter(models.DeviceOtaAssignment.state == assignment_state)
    if device_id:
        query = query.filter(models.DeviceOtaAssignment.device_id == device_id)
    assignments = query.order_by(models.DeviceOtaAssignment.requested_at.desc()).limit(limit).all()
    return [assignment_response(item) for item in assignments]


@router.post("/admin/ota/assignments/{assignment_id}/retry", response_model=schemas.OtaAssignmentResponse)
def retry_assignment(
    assignment_id: int,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    assignment = db.get(models.DeviceOtaAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="OTA assignment not found")
    if assignment.state == "success":
        raise HTTPException(status_code=409, detail="Successful assignment cannot be retried")
    other_active = db.query(models.DeviceOtaAssignment.id).filter(
        models.DeviceOtaAssignment.device_id == assignment.device_id,
        models.DeviceOtaAssignment.id != assignment.id,
        models.DeviceOtaAssignment.state.in_(ACTIVE_STATES),
    ).first()
    if other_active:
        raise HTTPException(status_code=409, detail="Device already has another active assignment")

    token, token_hash = new_download_token()
    assignment.download_token_hash = token_hash
    assignment.state = "assigned"
    assignment.progress = None
    assignment.completed_at = None
    assignment.last_error_code = None
    assignment.last_error_detail = None
    _audit(db, actor, "ota.assignment.retry", "device_ota_assignment", assignment.id)
    db.commit()
    db.refresh(assignment)
    if not publish_desired(assignment, token):
        raise HTTPException(status_code=503, detail="Assignment saved but MQTT publish is unavailable")
    return assignment_response(assignment)


@router.post("/admin/ota/assignments/{assignment_id}/cancel", response_model=schemas.OtaAssignmentResponse)
def cancel_assignment(
    assignment_id: int,
    actor: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
):
    assignment = db.get(models.DeviceOtaAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="OTA assignment not found")
    if assignment.state not in ACTIVE_STATES:
        raise HTTPException(status_code=409, detail="Only an active assignment can be cancelled")
    assignment.state = "cancelled"
    assignment.completed_at = datetime.utcnow()
    _audit(db, actor, "ota.assignment.cancel", "device_ota_assignment", assignment.id)
    db.commit()
    db.refresh(assignment)
    clear_desired(assignment.device.uid)
    return assignment_response(assignment)


@router.get("/ota/artifacts/{release_id}")
def download_artifact(
    release_id: int,
    authorization: str | None = Header(None),
    db: Session = Depends(database.get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing artifact token")
    token = authorization[7:]
    token_hash = hash_download_token(token)
    assignment = db.query(models.DeviceOtaAssignment).filter(
        models.DeviceOtaAssignment.release_id == release_id,
        models.DeviceOtaAssignment.state.in_(ACTIVE_STATES),
    ).all()
    matched = next(
        (item for item in assignment if hmac.compare_digest(item.download_token_hash, token_hash)),
        None,
    )
    if not matched:
        raise HTTPException(status_code=403, detail="Invalid artifact token")
    release = matched.release
    if release.status != "ready":
        raise HTTPException(status_code=404, detail="Firmware artifact is unavailable")
    path = artifact_path(release)
    if not path.is_file() or path.stat().st_size != release.size_bytes:
        raise HTTPException(status_code=404, detail="Firmware artifact is unavailable")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"aquanotes-{release.version}.bin",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
