# forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import Empleado
from .models import Reparacion
from .models import Etapa
from .models import Cotizacion
from .models import Cliente 
from .models import DetalleEtapa
from .models import Dispositivo

class DetalleEtapaForm(forms.ModelForm):
    class Meta:
        model = DetalleEtapa
        fields = ['fecha_inicio', 'fecha_fin', 'comentarios', 'etapa']
        widgets = {
            'fecha_inicio': forms.DateInput(attrs={'type': 'date'}),
            'fecha_fin': forms.DateInput(attrs={'type': 'date'}),
            'comentarios': forms.Textarea(attrs={'rows': 3}),
            'etapa': forms.Select(choices=Etapa.objects.all())  # Carga explícita de etapas
        }

class EmpleadoRegistroForm(UserCreationForm):
    class Meta:
        model = Empleado
        fields = ['username', 'email', 'first_name', 'last_name', 'rol', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre de usuario'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Correo electrónico'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apellido'}),
            'rol': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Rol'}),  # ← corregido aquí
            'password1': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Contraseña'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirmar contraseña'}),
        }

class EmpleadoLoginForm(AuthenticationForm):
    username = forms.CharField(label="Usuario", widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': 'Ingresa tu nombre de usuario'
    }))
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={
        'class': 'form-control', 'placeholder': 'Ingresa tu contraseña'
    }))


class ReparacionForm(forms.ModelForm):
    class Meta:
        model = Reparacion
        fields = ['fecha_ingreso', 'estado', 'dispositivo', 'empleado']
        widgets = {
            'fecha_ingreso': forms.DateInput(attrs={'type': 'date'}),
        }

class ResponderCotizacionForm(forms.ModelForm):
    class Meta:
        model = Cotizacion
        fields = ['mensaje_empleado']
        
class CotizacionForm(forms.ModelForm):
    # Campos para el cliente
    nombre = forms.CharField(max_length=100, label='Nombre')
    apellido = forms.CharField(max_length=100, label='Apellido')  # Nuevo campo de apellido
    email = forms.EmailField(label='Correo Electrónico')
    telefono = forms.CharField(max_length=15, label='Teléfono')

    # Nuevos campos para la cotización
    detalles_cotizacion = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'Explique por qué desea hacer una cotización'}),
        label='Detalles de la Cotización', required=True
    )
    problema_dispositivo = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describa el problema con el dispositivo'}),
        label='Problema con el dispositivo', required=True
    )

    # Nuevos campos para crear un dispositivo
    marca = forms.CharField(max_length=100, label='Marca del Dispositivo')
    modelo = forms.CharField(max_length=100, label='Modelo del Dispositivo')
    numero_serie = forms.CharField(max_length=100, label='Número de Serie del Dispositivo')
    descripcion = forms.CharField(widget=forms.Textarea, label='Descripción del Dispositivo')

    class Meta:
        model = Cotizacion
        fields = ['detalles_cotizacion', 'problema_dispositivo', 'marca', 'modelo', 'numero_serie', 'descripcion']  # Incluir los nuevos campos

    # Guardar los datos del cliente y el dispositivo
    def save(self, commit=True):
        # Guardamos la cotización pero no el cliente ni el dispositivo, ya que los crearemos
        cotizacion = super().save(commit=False)

        # Verificamos si el cliente ya existe, si no, lo creamos
        cliente, created = Cliente.objects.get_or_create(
            nombre=self.cleaned_data['nombre'],
            apellido=self.cleaned_data['apellido'],  # Usamos el apellido también
            email=self.cleaned_data['email'],
            telefono=self.cleaned_data['telefono'],
        )

        # Asignamos el cliente a la cotización
        cotizacion.cliente = cliente

        # Asignamos los detalles y el problema del dispositivo a la cotización
        cotizacion.mensaje_empleado = self.cleaned_data['detalles_cotizacion']  # Puede ser usado para mostrar los detalles de la cotización
        cotizacion.estado = 'Pendiente'  # Por defecto, la cotización está pendiente

        # Crear el nuevo dispositivo si no existe
        dispositivo = Dispositivo.objects.create(  # Usamos Dispositivo con mayúscula
            marca=self.cleaned_data['marca'],
            modelo=self.cleaned_data['modelo'],
            numero_serie=self.cleaned_data['numero_serie'],
            descripcion=self.cleaned_data['descripcion'],
            cliente=cliente  # Asociamos el dispositivo al cliente
        )

        # Asignar el dispositivo creado a la cotización
        cotizacion.dispositivo = dispositivo

        if commit:
            cotizacion.save()
        return cotizacion
