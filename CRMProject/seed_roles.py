import os
import django
from django.conf import settings

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CRMProject.settings')
django.setup()

from Authentication.models import LoginRole

def seed_roles():
    roles = [
        ('SUPERADMIN', 'Superadmin'),
        ('ADMIN', 'Admin'),
        ('SUPERVISOR', 'Supervisor'),
        ('AGENT', 'Agent'),
        ('CLIENT', 'Client'),
    ]

    # Iterate through all configured databases
    for db_alias in settings.DATABASES.keys():
        print(f"\n--- Seeding database: {db_alias} ---")
        for role_code, role_name in roles:
            # Use .using(db_alias) to target specific database
            role, created = LoginRole.objects.using(db_alias).get_or_create(name=role_code)
            if created:
                print(f"[{db_alias}] Created role: {role_code}")
            else:
                print(f"[{db_alias}] Role already exists: {role_code}")

if __name__ == "__main__":
    print("Start Seeding roles for all databases...")
    seed_roles()
    print("\nAll databases seeded successfully!")
