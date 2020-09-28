from functools import wraps
from flask import request, redirect, url_for, session
from string import ascii_letters, digits
import random
import boto3
import string
import pathlib
import os


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def random_str(n=10):
    string = ""
    for i in range(n):
        string += random.choice(ascii_letters+digits)
    return string


def upload_s3(request):
    s3 = boto3.resource("s3", aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"))
    name = random_str(10)
    s3.Bucket('note-flask-app').put_object(Key=f"{name}.{pathlib.Path(request.files['image'].filename).suffix}", Body=request.files["image"], ACL='public-read')
    return f"{name}.{pathlib.Path(request.files['image'].filename).suffix}"