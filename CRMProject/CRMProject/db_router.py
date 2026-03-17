import threading

# Global thread-local storage to hold the database name for the current request
thread_local = threading.local()

def set_db_for_request(db_name):
    setattr(thread_local, 'DB_NAME', db_name)

def get_db_for_request():
    return getattr(thread_local, 'DB_NAME', 'default')

class DatabaseRouter:
    """
    A router to dynamically select the database based on the current request context.
    The middleware sets the database name in thread-local storage.
    """
    def db_for_read(self, model, **hints):
        return get_db_for_request()

    def db_for_write(self, model, **hints):
        return get_db_for_request()

    def allow_relation(self, obj1, obj2, **hints):
        # Allow relations if they are in the same database context
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Allow migrations on all databases for all models
        # Note: You can tailor this if certain apps should only exist in certain DBs
        return True
