from flask import Flask
from models import db

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-before-demo"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///complaints.db"
db.init_app(app)


@app.route("/")
def home():
    return "Complaint dashboard is running!"