from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
import uuid
from datetime import timedelta
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager

class LoginRole(models.Model):
    ROLE_CHOICES = (
        ('SUPERADMIN', 'Superadmin'),
        ('ADMIN', 'Admin'),
        ('SUPERVISOR', 'Supervisor'),
        ('AGENT', 'Agent'),
        ('CLIENT', 'Client'),
    )

    name = models.CharField(max_length=20, choices=ROLE_CHOICES, unique=True)

    def __str__(self):
        return self.name


class LoginUserManager(BaseUserManager):

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        #  Extract role BEFORE creating user
        role_value = extra_fields.pop("role", None)

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)

        #  Assign role correctly
        if role_value:
            if isinstance(role_value, LoginRole):
                user.role = role_value
            else:
                user.role = LoginRole.objects.get(id=int(role_value))

        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if not extra_fields.get("role"):
            extra_fields["role"] = LoginRole.objects.get(name="SUPERADMIN")

        return self.create_user(email, password, **extra_fields)

class LoginUser(AbstractBaseUser, PermissionsMixin):
    asc_code = models.CharField(max_length=255)
    asc_name = models.CharField(max_length=255)
    asc_location = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone_no =models.CharField(max_length=10)
    password = models.CharField(max_length=255)
    role = models.ForeignKey(LoginRole, on_delete=models.PROTECT,null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False) 
    is_superuser = models.BooleanField(default=False) 
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_members"
    )
    objects = LoginUserManager()  
    reset_token = models.CharField(max_length=64, null=True, blank=True)
    reset_token_expiry = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['asc_code', 'asc_name', 'asc_location', 'role']



    #  Reset token
    def generate_reset_token(self):
        self.reset_token = uuid.uuid4().hex
        self.reset_token_expiry = timezone.now() + timedelta(minutes=15)
        self.save(update_fields=["reset_token", "reset_token_expiry"])
        return self.reset_token

    def is_reset_token_valid(self):
        return (
            self.reset_token
            and self.reset_token_expiry
            and timezone.now() <= self.reset_token_expiry
        )

    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expiry = None
        self.save(update_fields=["reset_token", "reset_token_expiry"])

    def __str__(self):
        return self.email
