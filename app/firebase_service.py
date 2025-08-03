import firebase_admin
from firebase_admin import credentials, messaging
from firebase_admin.exceptions import FirebaseError
import logging
import os

logger = logging.getLogger(__name__)

def initialize_firebase():
    try:
        if not firebase_admin._apps:
            # Path ke file service account
            current_dir = os.path.dirname(os.path.abspath(__file__))
            cred_path = os.path.join(current_dir, 'firebase', 'aqua-notes-firebase-adminsdk-fbsvc-6de08d39b2.json')
            
            if not os.path.exists(cred_path):
                logger.error("Firebase service account file not found")
                return False
                
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase app initialized")
            return True
    except Exception as e:
        logger.error(f"Error initializing Firebase: {str(e)}")
        return False

# Inisialisasi saat modul dimuat
initialize_firebase()

def send_fcm_notification(user_fcm_token: str, title: str, body: str, data: dict = None):
    if not user_fcm_token:
        logger.warning("No FCM token, skipping notification")
        return False
    
    try:
        # Buat payload notifikasi
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            token=user_fcm_token,
            data=data or {},
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default")
                )
            ),
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="sensor_alerts"
                )
            )
        )
        
        # Kirim notifikasi
        response = messaging.send(message)
        logger.info(f"FCM sent to {user_fcm_token[:10]}...: {response}")
        return True
        
    except FirebaseError as e:
        logger.error(f"Firebase error: {str(e)}")
    except ValueError as e:
        logger.error(f"Invalid FCM token: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
    
    return False