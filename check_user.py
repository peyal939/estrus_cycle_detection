import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'harness_data_portal.settings')
django.setup()

from django.contrib.auth import authenticate
from django.contrib.auth.models import User

username = 'admin'
# We can't know the password the user typed, but we can check if the user exists
# and is active.
try:
    user = User.objects.get(username=username)
    print(f"User '{username}' exists.")
    print(f"Is active: {user.is_active}")
    print(f"Is superuser: {user.is_superuser}")
    print(f"Password hash: {user.password[:20]}...") # Just to see if it has a hash
except User.DoesNotExist:
    print(f"User '{username}' does not exist.")

print("\nTo test authentication, I need the password.")
# I can't prompt interactively easily here without the user running it.
# But I can ask the user to run this script or I can try to reset the password to a known value.
