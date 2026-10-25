"""
Case-insensitives Login: 'Joerg.Bernau' == 'joerg.bernau'.

Der Anmeldename wird unabhängig von Groß-/Kleinschreibung geprüft. Angelegt
werden Namen ohnehin klein (vorname.nachname); dieser Backend erlaubt zusätzlich
die Eingabe in beliebiger Schreibweise.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = UserModel._default_manager.get(username__iexact=username)
        except UserModel.DoesNotExist:
            UserModel().set_password(password)  # Timing-Angriff abmildern
            return None
        except UserModel.MultipleObjectsReturned:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
