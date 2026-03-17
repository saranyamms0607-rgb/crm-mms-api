from .db_router import set_db_for_request

class DatabaseSelectionMiddleware:
    """
    Middleware that selects the database for the current request based on a custom header.
    Expects 'X-DB-Name' header with values 'default', 'domestic', or 'international'.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Check Headers or Direct Query Param
        db_name = request.headers.get('X-DB-Name') or request.GET.get('db_name')
        
        # 2. If missing, look inside the 'next' parameter (common for Admin redirects)
        if not db_name:
            next_url = request.GET.get('next')
            if next_url and 'db_name=' in next_url:
                import urllib.parse
                parsed_next = urllib.parse.urlparse(next_url)
                next_params = urllib.parse.parse_qs(parsed_next.query)
                if 'db_name' in next_params:
                    db_name = next_params['db_name'][0]
        
        # 3. If still missing, check Cookie
        if not db_name:
            db_name = request.COOKIES.get('selected_db')

        # 4. Default to 'default'
        if not db_name:
            db_name = 'default'
            
        # Security: restrict to valid database identifiers
        valid_dbs = ['default', 'domestic', 'international']
        if db_name not in valid_dbs:
            db_name = 'default'
            
        # Set the database for the current thread/request
        set_db_for_request(db_name)
        
        response = self.get_response(request)

        # 5. Persist the choice in a cookie so admin links work
        # We only set the cookie if it's different or if it was explicitly requested
        if request.GET.get('db_name') or request.COOKIES.get('selected_db') != db_name:
            response.set_cookie('selected_db', db_name, max_age=3600*24, samesite='Lax')

        return response
