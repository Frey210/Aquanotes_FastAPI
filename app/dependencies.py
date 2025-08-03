from app.database import get_db
from app.auth import get_current_user

# Jika perlu dependency yang digunakan di banyak router
common_deps = {
    "db": Depends(get_db),
    "current_user": Depends(get_current_user)
}