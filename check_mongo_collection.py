import os
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

def check_collection():
    uri = os.getenv('MONGO_URI')
    client = MongoClient(uri)
    db = client['harnesstag']
    
    print("Listing collections in 'harnesstag' database:")
    for collection_name in db.list_collection_names():
        print(f"- {collection_name}")
        options = db.get_collection(collection_name).options()
        print(f"  Options: {options}")
        
    # Try a test insert
    print("\nAttempting test insert into 'iotdata'...")
    try:
        collection = db['iotdata']
        # The collection options show timeField is '"time"' (with quotes)
        test_doc = {
            "tagID": 9999,
            '"time"': datetime.now(timezone.utc),
            "test": True
        }
        print(f"Inserting: {test_doc}")
        result = collection.insert_one(test_doc)
        print(f"Insert successful! _id: {result.inserted_id}")
    except Exception as e:
        print(f"Insert failed: {e}")

if __name__ == "__main__":
    check_collection()
