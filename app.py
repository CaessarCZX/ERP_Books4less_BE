import os
from app import create_app
from flask_cors import CORS

app = create_app()
CORS(app)
# CORS(app, resources={r"/api/*": {"origins": "http://localhost:5173"}}, supports_credentials=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 443))  
    app.run(host="20.119.136.20", port=port)
