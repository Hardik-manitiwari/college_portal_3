from workers import wsgi
from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/api/status")
def status():
    return jsonify({
        "status": "D1 port pending",
        "message": "Replace Flask-SQLAlchemy routes with D1 queries before deployment",
    })

Default = wsgi.entrypoint(app)
