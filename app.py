from app import create_app
from flask_cors import CORS
from config.config import Config

app = create_app()

#CORS(app)

CORS(
        app,
        resources={r"/api/*": {"origins": Config.CORS_ALLOWED_ORIGINS}},
        methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
        allow_headers=["Content-Type","Authorization"],
        supports_credentials=True
)

if __name__ == "__main__":
    port = int(Config.PORT)
    app.run(port=port)
