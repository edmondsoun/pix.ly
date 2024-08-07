# FLASK IMPORTS
import os
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, request

# FILE HANDLING AND RENDERING IMPORTS
import base64
from urllib.request import urlopen
from werkzeug.utils import secure_filename
from sqlalchemy import update, or_


# MODEL IMPORTS
from models import db, connect_db, UserImage

# HELPER FUNCTIONS
from boto_model import upload_file
from filters import *
from utils import *

load_dotenv()

# DB SETUP

database_url = os.environ.get('DATABASE_URL', "postgresql:///pixly")
database_url = database_url.replace('postgres://', 'postgresql://')

app = Flask(__name__)

# CONFIG
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = True

app.config['DO_ACCESS_KEY_ID'] = os.environ.get('DO_ACCESS_KEY_ID', '')
app.config['DO_SECRET_ACCESS_KEY'] = os.environ.get('DO_SECRET_ACCESS_KEY', '')
app.config['BUCKET'] = os.environ.get('BUCKET', '')
app.config['SECRET_KEY'] = "SECRET!"

# GLOBAL CONSTANTS
BUCKET = os.environ.get('BUCKET', '')
BASE_URL = os.environ.get('BASE_URL', "localhost")

connect_db(app)

# db.create_all()


##################### ROUTES #####################

##################### HOMEPAGE #####################

@app.get('/')
def show_images():
    """
    Show all images where 'published=True'.
    If query parameters are provided, filter based on partial match to image description
    and 'published=True'.
    """

    hasSearch = request.args

    if hasSearch:
        searchTerm = request.args['search']

        all_images = UserImage.query.filter(or_(
            UserImage.description.ilike(f"%{searchTerm}%"),
            UserImage.exifdata.ilike(f"%{searchTerm}%")),
            UserImage.published == True).all()

    else:
        all_images = UserImage.query.filter(
            UserImage.published == True).all()

    timestamped_images = []

    for image in all_images:
        timestamped_images.append({"url":f'{BASE_URL}{BUCKET}/{image.filename}',"timestamp":image.timestamp})

    return render_template('image_listing.html', all_images = timestamped_images)


##################### UPLOAD #####################

@app.post('/upload')
def process_upload_form():
    """
    Upload image to DO, store filename and other properties in database for later reference.
    Redirects to edit page or, if invalid filename is provided, redirect to home.
    """

    file = request.files['file']

    if file.filename == '':
        return redirect('/')

    extra_args = {'ContentType': file.content_type, 'ACL': 'public-read'}

    file_with_exif_dict = get_exif_data(file)
    file2 = file_with_exif_dict['file']
    exif_str = file_with_exif_dict['exif']

    if file and allowed_file(file.filename):

        unique_filename = generate_unique_filename(file.filename)
        filename = secure_filename(unique_filename)

        #upload to DO
        upload_file(file2, BASE_URL, filename, extra_args)

        #add to DB
        new_image = UserImage(
            filename=filename,
            published=False,
            content_type=file.content_type,
            exifdata=exif_str
        )

        db.session.add(new_image)
        db.session.commit()
        return redirect(f'edit/{filename}')

    return redirect('/')


##################### EDIT/PUBLISH #####################

@app.get('/edit/<filename>')
def display_edit(filename):
    '''
    Diplay original photo, edited photo result(if applicable), and form to edit.
    '''

    og_image = f'{BASE_URL}{BUCKET}/{filename}'

    try:
        filter = request.args['filter']
        data = set_filter(urlopen(og_image), filter)
        encoded_img_data = base64.b64encode(data.getvalue())
        new_image = encoded_img_data.decode('utf-8')
    except:
        filter = 'none'
        new_image = None

    return render_template(
        'edit_page.html',
        og_image=og_image,
        filename=filename,
        filter=filter,
        encoded_image=new_image
        )

@app.post('/edit/<filename>/<filter>')
def publish_edit(filename, filter):
    '''
    Uploads edited photo to DO and returns to homepage.
    If no edits are requested, update original image 'published' value to 'True'
    and redirect to home.
    '''

    og_image = f'{BASE_URL}{BUCKET}/{filename}'
    og_file = UserImage.query.get(filename)

    description = request.form['description']

    try:
        data = set_filter(urlopen(og_image), filter)
    except:
        image = UserImage.query.get(filename)
        image.published = True
        image.description = description
        db.session.commit()
        return redirect('/')


    #add to DO:
    extra_args = {'ContentType': og_file.content_type, 'ACL': 'public-read'}
    unique_filename = generate_unique_filename(filename)
    secured_filename = secure_filename(unique_filename)

    upload_file(data, BASE_URL, secured_filename, extra_args)

    #add to DB:
    edited_image = UserImage(filename=secured_filename,
                             published=True,
                             content_type=og_file.content_type,
                             filter=filter,
                             description=description,
                             exifdata=og_file.exifdata)
    db.session.add(edited_image)
    db.session.commit()

    return redirect('/')