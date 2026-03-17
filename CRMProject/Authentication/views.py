from django.http import HttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .models import LoginUser
import json
from rest_framework import status
import logging
import uuid
from django.core.mail import send_mail
# from django.utils.timezone import now
from datetime import timedelta, timezone
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
logger = logging.getLogger(__name__)


from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .authentication import LoginUserJWTAuthentication

from django.conf import settings 
frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
class MyProtectedView(APIView):
    authentication_classes = [LoginUserJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user  # This is now a LoginUser instance
        return Response({
            "email": user.email,
            "name": user.asc_name,
            "role": user.role.name
        },status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class LoginView(View):

    def post(self, request):
       

        try:
            data = json.loads(request.body)
            email = data.get("email")
            password = data.get("password")
        
            if not email or not password:
                return HttpResponse(
                    json.dumps({
                        "status": "fail",
                        "message": "Email and password required"
                    }),
                    content_type="application/json",
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Search across all three databases sequentially
            databases = ['default', 'domestic', 'international']
            user = None
            found_in_db = None

            for db in databases:
                try:
                    user_qs = LoginUser.objects.using(db).select_related("role").filter(
                        email=email,
                        is_active=True
                    )
                    if user_qs.exists():
                        user = user_qs.first()
                        found_in_db = db
                        break
                except Exception:
                    continue

            if not user:
                logger.warning(f"Login failed: User {email} not found in any database")
                return HttpResponse(
                    json.dumps({
                        "status": "fail",
                        "message": "User not found"
                    }),
                    content_type="application/json",
                    status=status.HTTP_404_NOT_FOUND
                )

        

            if not user.check_password(password):
                return HttpResponse(
                    json.dumps({
                        "status": "fail",
                        "message": "Invalid credentials",
                    }),
                    content_type="application/json",
                    status=status.HTTP_401_UNAUTHORIZED
                )

            refresh = RefreshToken.for_user(user)
            user_data={
                "user_id": user.id,
                "email": user.email,
                "role": user.role.name,
                "asc_name": user.asc_name,
                "asc_code": user.asc_code,
                "asc_location": user.asc_location,
                "db_silo": found_in_db # Tell the frontend which DB to use for future requests
            }

            return HttpResponse(
                json.dumps({
                    "status": "success",
                    "message": "Login successful",
                    "data": user_data,
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "expires_in": int(refresh.access_token.lifetime.total_seconds()),
                }),
                content_type="application/json",
                status=status.HTTP_200_OK
            )

        except json.JSONDecodeError:
           
            return HttpResponse( json.dumps({
                        "status": "fail",
                        "message": "Invalid JSON format"
                    }),
                    content_type="application/json",
                    status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return HttpResponse( json.dumps({
                        "status": "Error",
                        "message":f"Server error: {str(e)}"
                    }),
                    content_type="application/json",
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request):
        return HttpResponse("POST method required", status=405)



@method_decorator(csrf_exempt, name="dispatch")
class LogoutView(View):

    def post(self, request):
        return HttpResponse(
            json.dumps({
                "status": "success",
                "message": "Logout successful"
            }),
            content_type="application/json",
            status=status.HTTP_200_OK
        )

    def get(self, request):
        return HttpResponse("POST method required", status=405)

@method_decorator(csrf_exempt, name="dispatch")
class ForgotPasswordView(View):

    def post(self, request):
        try:
            data = json.loads(request.body)
            email = data.get("email")

            # Search across all three databases
            databases = ['default', 'domestic', 'international']
            user = None
            found_in_db = None

            for db in databases:
                try:
                    user_qs = LoginUser.objects.using(db).filter(email=email, is_active=True)
                    if user_qs.exists():
                        user = user_qs.first()
                        found_in_db = db
                        break
                except Exception:
                    continue

            if not user:
                return HttpResponse(
                    json.dumps({
                        "status": "fail",
                        "message": "Email not registered"
                    }),
                    content_type="application/json",
                    status=status.HTTP_404_NOT_FOUND
                )

            token = str(uuid.uuid4())
            user.reset_token = token
            user.reset_token_expiry = timezone.now() + timedelta(minutes=15)
            # Save to the specific database where the user was found
            user.save(using=found_in_db)

            reset_link = f"{frontend_url}/reset-password/{token}"

            send_mail(
                "Reset Your Password",
                f"Click the link to reset your password:\n{reset_link}",
                None,
                [email],
                fail_silently=False,
            )

            return HttpResponse(
                json.dumps({
                    "status": "success",
                    "message": "Reset link sent to email"
                }),
                content_type="application/json",
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return HttpResponse(
                json.dumps({"status": "error", "message": str(e)}),
                content_type="application/json",
                status=500
            )

@method_decorator(csrf_exempt, name="dispatch")
class ResetPasswordView(View):

    def post(self, request, token):
        try:
            data = json.loads(request.body)
            new_password = data.get("password")

            # Search across all databases for the user with this token
            databases = ['default', 'domestic', 'international']
            user = None
            found_in_db = None

            for db in databases:
                try:
                    user_qs = LoginUser.objects.using(db).filter(
                        reset_token=token,
                        reset_token_expiry__gte=timezone.now()
                    )
                    if user_qs.exists():
                        user = user_qs.first()
                        found_in_db = db
                        break
                except Exception:
                    continue

            if not user:
                return HttpResponse(
                    json.dumps({
                        "status": "fail",
                        "message": "Invalid or expired token"
                    }),
                    content_type="application/json",
                    status=status.HTTP_400_BAD_REQUEST
                )

            user.set_password(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            user.save(using=found_in_db)

            return HttpResponse(
                json.dumps({
                    "status": "success",
                    "message": "Password reset successful"
                }),
                content_type="application/json",
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return HttpResponse(
                json.dumps({"status": "error", "message": str(e)}),
                content_type="application/json",
                status=500
            )


class UserDropdownView(GenericAPIView):

    def get(self, request):
        search = request.GET.get("search", "")
        limit = int(request.GET.get("limit", 20))

        users = LoginUser.objects.filter(
            is_active=True,
            role__name="AGENT"
        )

        if search:
            users = users.filter(
                Q(email__icontains=search) |
                Q(asc_name__icontains=search) 
            )

        users = users.order_by("asc_name")[:limit]

        data = [
            {
                "id": user.id,
                "email": user.email,
                "name": user.asc_name,
            }
            for user in users
        ]

    
        return HttpResponse(
                        json.dumps({
                            "status": "success",
                            "message": "Agent list fetched successfully",
                            "data": data
                        }),
                        content_type="application/json",
                        status=status.HTTP_200_OK)
    