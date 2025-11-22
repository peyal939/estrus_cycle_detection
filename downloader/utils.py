import os
from pymongo import MongoClient
from django.conf import settings

def get_db_handle():
    client = MongoClient(os.getenv('MONGO_URI'))
    db = client['harnesstag']
    return db, client
