from datetime import datetime
from datetime import date
from django.utils import timezone
# Django core
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import IntegrityError, models
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.timezone import localtime
from django.core.mail import send_mail
from django.db import connection
import os

# Librería externa
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from sib_api_v3_sdk import ApiClient, Configuration, SendSmtpEmail, TransactionalEmailsApi


# App interna
from .models import Cliente, Dispositivo, Reparacion, Empleado, DetalleEtapa, Etapa, Notificacion, Cotizacion
from .forms import EmpleadoRegistroForm, EmpleadoLoginForm, ReparacionForm, DetalleEtapaForm
from .forms import ResponderCotizacionForm, CotizacionForm

import stripe
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse


from .models import Empleado, Reparacion
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.template.loader import render_to_string
from io import BytesIO

TEMPLATE_REPARACIONES = 'miApp/reparaciones.html'

def reportepdf(request, empleado_id):
    empleado = get_object_or_404(Empleado, id=empleado_id)

    # Reparaciones EN PROCESO (excluye Finalizado y Entrega)
    reparaciones = Reparacion.objects.filter(
        empleado=empleado
    ).exclude(
        estado__in=["Finalizado", "Entrega"]
    )

    # Reparaciones FINALIZADAS o ENTREGADAS — ahora filtradas por el mismo empleado
    historial = Reparacion.objects.filter(
        empleado=empleado,
        estado__in=["Finalizado", "Entrega"]
    )

    context = {
        'empleado': empleado,
        'reparaciones': reparaciones,
        'historial': historial,
    }

    html = render_to_string('miApp/reportepdf.html', context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="reporte_empleado_{empleado.id}.pdf"'
    pisa.CreatePDF(BytesIO(html.encode("utf-8")), dest=response, encoding='utf-8')

    return response





def reporte_empleado(request, empleado_id):
    # Obtén el empleado usando su ID (si existe)
    empleado = get_object_or_404(Empleado, id=empleado_id)
    
    # Obtén las reparaciones de ese empleado
    reparaciones = Reparacion.objects.filter(empleado=empleado)

    # Generar reporte de manera sencilla
    return render(request, 'miApp/reporte_empleado.html', {
        'empleado': empleado,
        'reparaciones': reparaciones
    })

def crear_cotizacion(request):
    if request.method == 'POST':
        form = CotizacionForm(request.POST)
        if form.is_valid():
            cotizacion = form.save(commit=False)
            cotizacion.estado = 'Pendiente'  # Por defecto, la cotización está pendiente
            cotizacion.save()
            return redirect('cotizacion_exito')  # Redirigir a una página de éxito o confirmación
    else:
        form = CotizacionForm()

    return render(request, 'miApp/cotizacion.html', {'form': form})


def cotizaciones_pendientes(request):
    cotizaciones = Cotizacion.objects.filter(estado='Pendiente')
    return render(request, 'miApp/cotizaciones_pendientes.html', {'cotizaciones': cotizaciones})

def responder_cotizacion(request, cotizacion_id):
    cotizacion = get_object_or_404(Cotizacion, id=cotizacion_id)

    if request.method == 'POST':
        # Obtener datos del formulario
        nombre = request.POST.get('nombre')
        email = request.POST.get('email')
        mensaje = request.POST.get('mensaje')

        # Contenido del mensaje para el correo
        contenido = f"""
        <h2>Respuesta a tu cotización</h2>
        <p><strong>Nombre:</strong> {nombre}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Mensaje:</strong><br>{mensaje}</p>
        <p><strong>Detalles de la cotización:</strong><br>
        ID de Cotización: {cotizacion.id}<br>
        Cliente: {cotizacion.cliente.nombre} {cotizacion.cliente.apellido}<br>
        Producto: {cotizacion.dispositivo.marca}</p>
        """

        # Configuración de Brevo (Sendinblue)
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

        # Definir el correo a enviar
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email, "name": nombre}],
            sender={"email": "jahfixmanager@gmail.com", "name": "JahFix Manager"},
            subject="Respuesta a tu cotización",
            html_content=contenido
        )

        try:
            # Intentar enviar el correo
            api_response = api_instance.send_transac_email(send_smtp_email)
            if hasattr(api_response, 'message_id'):
                # Si el correo fue enviado correctamente, actualizar la cotización
                cotizacion.estado = 'Respondida'  # Actualizar el estado de la cotización
                cotizacion.fecha_respuesta = localtime()  # Registrar la fecha de respuesta
                cotizacion.mensaje_empleado = mensaje  # Guardar el mensaje del empleado en la cotización
                cotizacion.save()  # Guardar la cotización actualizada

                return redirect('cotizaciones_pendientes')  # Redirigir a la lista de cotizaciones
            else:
                return HttpResponse(f'Correo enviado correctamente. Respuesta: {api_response}')
        except ApiException as e:
            return HttpResponse(f'Error al enviar el correo: {e}')

    else:
        form = ResponderCotizacionForm(instance=cotizacion)

    return render(request, 'miApp/responder_cotizacion.html', {'form': form, 'cotizacion': cotizacion})

def cotizacion_exito(request):
    return render(request, 'miApp/cotizacion_exito.html')


#lo relacionado a reparación 

def reparacion_detalle(request, id):
    try:
        reparacion = Reparacion.objects.get(id=id)
    except Reparacion.DoesNotExist:
        return render(request, 'miApp/error.html', {'message': 'Reparación no encontrada'})

    etapas = reparacion.detalleetapa_set.order_by('-fecha_inicio')  # ⬅️ NUEVO

    if request.method == 'POST':
        form = DetalleEtapaForm(request.POST)
        if form.is_valid():
            detalle = form.save(commit=False)
            detalle.reparacion = reparacion
            detalle.empleado = request.user
            detalle.save()
            reparacion.estado = detalle.etapa.nombre_etapa
            reparacion.save()
            return redirect('reparacion_detalle', id=reparacion.id)
    else:
        form = DetalleEtapaForm()
        etapas_disponibles = Etapa.objects.exclude(nombre_etapa__iexact='Entrega').exclude(nombre_etapa__iexact='Reparación')
        form.fields['etapa'].queryset = etapas_disponibles

    return render(request, 'miApp/reparacion_detalle.html', {
        'reparacion': reparacion,
        'form': form,
        'etapas': etapas  # ⬅️ NUEVO
    })


#API Pago

stripe.api_key = settings.STRIPE_SECRET_KEY

@csrf_exempt
def create_checkout_session(request):
    try:
        id_reparacion = request.GET.get('id_reparacion')

        # BASE_URL
        BASE_URL = os.getenv('BASE_URL', 'http://localhost:8000')

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Aprobación de reparación',
                    },
                    'unit_amount': 5000,  # $50.00 USD
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{BASE_URL}/success/?id_reparacion={id_reparacion}',
            cancel_url=f'{BASE_URL}/cancel/',
        )
        return JsonResponse({'id': session.id})
    except Exception as e:
        return JsonResponse({'error': str(e)})


def success(request):
    id_reparacion = request.GET.get('id_reparacion')
    if id_reparacion:
        reparacion = get_object_or_404(Reparacion, id=id_reparacion)
        reparacion.estado = 'Reparación'
        reparacion.save()
    messages.success(request, '✅ ¡Pago exitoso y reparación aprobada!')
    return redirect(f"{reverse('seguimiento')}?id_reparacion={id_reparacion}")


# tambien relacionado a reparación 
def lista_reparaciones(request):
    # request.user ya es un Empleado
    reparaciones = Reparacion.objects.select_related(
        'dispositivo__cliente', 'empleado'
    ).filter(empleado=request.user).exclude(estado='Entrega')

    context = {
        'reparaciones': reparaciones
    }
    return render(request, 'miApp/reparaciones.html', context)


# relacionado a la API de Pagos
def payment_success(request):
    id_reparacion = request.GET.get('id_reparacion')

    if id_reparacion:
        reparacion = get_object_or_404(Reparacion, id=id_reparacion)
        
        # Actualizamos el estado a 'Pagado' para que el trigger se active
        reparacion.estado = 'Pagado'
        reparacion.save()
        
        # Esto activará el trigger que cambiará el estado a 'Entrega'
        messages.success(request, '✅ Pago exitoso. Reparación aprobada.')
        return redirect(f"{reverse('seguimiento')}?id_reparacion={id_reparacion}")

    return HttpResponse("Pago realizado, pero no se encontró la reparación.")




# Sistema
def es_admin(user):
    return user.is_superuser or user.rol == 'admin' 



# mas relaciones a reparación
def reparaciones(request):
    try:
        empleado = Empleado.objects.get(user=request.user)
        reparaciones = Reparacion.objects.filter(empleado=empleado)
        print(f"Reparaciones: {reparaciones}")
        for r in reparaciones:
            print(f"Dispositivo: {r.dispositivo.marca}, Cliente: {r.dispositivo.cliente.nombre}")
            print(f"Empleado: {r.empleado.nombre}")
    except Empleado.DoesNotExist:
        reparaciones = []
        print("No se encontró un empleado para el usuario logueado")

    return render(request, 'reparaciones.html', {'reparaciones': reparaciones})

#pago
def pagar(request):
    return render(request, 'miApp/pagar.html', {
        'STRIPE_PUBLIC_KEY': settings.STRIPE_PUBLIC_KEY
    })

# redirecciones simples a html 
def index(request):
    return render(request, 'miApp/index.html')


def condiciones_servicio(request):
    return render(request, 'miApp/Condiciones.html')

def sobre_nosotros(request):
    return render(request, 'miApp/sobre_nosotros.html')

def contactanos(request):
    return render(request, 'miApp/contactanos.html')

# esto esta relacionado a brevo 

def notificacion(request, id):
    reparacion = get_object_or_404(Reparacion, id=id)

    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        email = request.POST.get('email')
        mensaje = request.POST.get('mensaje')

        contenido = f"""
        <h2>Nuevo mensaje de contacto</h2>
        <p><strong>Nombre:</strong> {nombre}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Mensaje:</strong><br>{mensaje}</p>
        <p><strong>Detalles de la reparación:</strong><br>
        ID de Reparación: {reparacion.id}<br>
        Cliente: {reparacion.dispositivo.cliente.nombre} {reparacion.dispositivo.cliente.apellido}<br>
        Dispositivo: {reparacion.dispositivo.marca} {reparacion.dispositivo.modelo}</p>
        """

        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY  
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email, "name": nombre}],
            sender={"email": "jahfixmanager@gmail.com", "name": "JahFix Manager"},
            subject="Formulario de Contacto - Django",
            html_content=contenido
        )

        try:
            api_response = api_instance.send_transac_email(send_smtp_email)
            if hasattr(api_response, 'message_id'):
                return HttpResponse(f'Correo enviado correctamente. ID: {api_response.message_id}')
            return HttpResponse(f'Correo enviado correctamente. Respuesta: {api_response}')
        except ApiException as e:
            return HttpResponse(f'Error al enviar el correo: {e}')

    return render(request, 'miApp/notificacion.html', {
        'reparacion_id': reparacion.id
    })

# tambien brevo
def notificacioncli(request, id):
    reparacion = get_object_or_404(Reparacion, id=id)

    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        email = request.POST.get('email')
        mensaje = request.POST.get('mensaje')

        contenido = f"""
        <h2>Nuevo mensaje de contacto</h2>
        <p><strong>Nombre:</strong> {nombre}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Mensaje:</strong><br>{mensaje}</p>
        <p><strong>Detalles de la reparación:</strong><br>
        ID de Reparación: {reparacion.id}<br>
        Cliente: {reparacion.dispositivo.cliente.nombre} {reparacion.dispositivo.cliente.apellido}<br>
        Dispositivo: {reparacion.dispositivo.marca} {reparacion.dispositivo.modelo}</p>
        """

        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY  
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email, "name": nombre}],
            sender={"email": "jahfixmanager@gmail.com", "name": "JahFix Manager"},
            subject="Formulario de Contacto - Django",
            html_content=contenido
        )

        try:
            api_response = api_instance.send_transac_email(send_smtp_email)

            reparacion.estado = 'Entrega'
            reparacion.save()

            return redirect('reparaciones')  

        except ApiException as e:
            return HttpResponse(f'Error al enviar el correo: {e}')

    return render(request, 'miApp/notificacioncli.html', {
        'reparacion_id': reparacion.id
    })

# Esto es para registrar empleado
def registro_empleado(request):
    if request.method == 'POST':
        form = EmpleadoRegistroForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = EmpleadoRegistroForm()
    return render(request, 'miApp/registro.html', {'form': form})

# El login del empleado
def login_view(request):
    if request.method == 'POST':
        form = EmpleadoLoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            
            user = authenticate(request, username=username, password=password)
            print(f"Intento de login - Usuario: {username}, Autenticado: {user is not None}")  # DEBUG

            if user is not None:
                login(request, user)
                return redirect('perfilempleado')
            else:
                form.add_error(None, "Usuario o contraseña incorrectos.")
    else:
        form = EmpleadoLoginForm()

    return render(request, 'miApp/login.html', {'form': form})

# parte de las vistas de usuario
@login_required
def dashboard(request):
    # Contadores
    total_reparaciones = Reparacion.objects.count()  # Total de reparaciones en la base de datos
    en_proceso = Reparacion.objects.filter(estado__icontains="proceso").count()  # Reparaciones en proceso
    pendientes = Reparacion.objects.filter(estado__icontains="pendiente").count()  # Reparaciones pendientes
    completadas = Reparacion.objects.filter(estado__icontains="Entrega").count()  # Reparaciones completadas
    total_notificaciones = Notificacion.objects.count()  # Total de notificaciones

    # Reparaciones recientes (últimas 5)
    reparaciones_recientes = Reparacion.objects.select_related('dispositivo', 'dispositivo__cliente').order_by('-fecha_ingreso')[:5]

    # Contexto para pasar a la plantilla
    contexto = {
        'total_reparaciones': total_reparaciones,
        'en_proceso': en_proceso,
        'pendientes': pendientes,
        'completadas': completadas,
        'total_notificaciones': total_notificaciones,
        'reparaciones_recientes': reparaciones_recientes,
    }

    return render(request, 'miApp/dashboard.html', contexto)

# parte del perfil del usuario
def historial(request):
    historial = Reparacion.objects.select_related(
        'dispositivo__cliente', 'empleado'
    ).filter(estado='Entrega')

    context = {
        'historial': historial
    }
    return render(request, 'miApp/historial.html', context)

# relacionado a reparacion
def reabrir_reparacion(request, id):
    reparacion = get_object_or_404(Reparacion, id=id)
    reparacion.estado = "Reparación"
    reparacion.save()
    return redirect('reparaciones')

# relacionado a la gestión del cliente

def seguimiento(request):
    id_reparacion = request.GET.get('id_reparacion')

    if id_reparacion:
        reparacion = get_object_or_404(Reparacion, id=id_reparacion)

        accion = request.GET.get('accion')
        if accion == 'rechazar':
            razon_rechazo = request.GET.get('razon_rechazo')

            # Actualizar el estado de la reparación
            reparacion.estado = 'Diagnóstico'
            reparacion.save()

            # Obtener el empleado asignado a la reparación
            empleado = reparacion.empleado  # Aquí asumo que la reparación tiene un campo 'empleado'

            # Buscar la etapa correspondiente "Diagnóstico" en tu modelo Etapa
            etapa_diagnostico = get_object_or_404(Etapa, nombre_etapa='Diagnóstico')

            # Crear una nueva etapa para la reparación con el estado "diagnóstico"
            nueva_etapa = DetalleEtapa(
                fecha_inicio=timezone.now(),
                etapa=etapa_diagnostico,  # Aquí asignamos la etapa "Diagnóstico"
                reparacion=reparacion,
                comentarios="Rechazo de cliente, esperando diagnóstico.",
                comentario_rechazo=razon_rechazo,
                empleado=empleado  # Asignamos el empleado de la reparación
            )
            nueva_etapa.save()

            messages.success(request, '⚠️ Reparación rechazada. El equipo continuará trabajando en el diagnóstico.')

            return redirect(f"{reverse('seguimiento')}?id_reparacion={id_reparacion}")

        # Filtrar etapas sin duplicados
        etapas = reparacion.detalleetapa_set.all()

        # Filtrar duplicados
        etapas_unicas = []
        seen = set()
        for etapa in etapas:
            if etapa.etapa.nombre_etapa not in seen:
                etapas_unicas.append(etapa)
                seen.add(etapa.etapa.nombre_etapa)

        return render(request, 'miApp/seguimiento.html', {
            'reparacion': reparacion,
            'etapas': etapas_unicas,
            'id_reparacion': id_reparacion,
            'STRIPE_PUBLIC_KEY': settings.STRIPE_PUBLIC_KEY
        })

    return render(request, 'miApp/seguimiento.html')

# asignacion de reparaciones
def asignar(request):
    if request.method == 'POST':
        try:
            # Obtener los datos del formulario
            fecha_ingreso = request.POST['fecha_ingreso']
            marca = request.POST['marca']
            modelo = request.POST['modelo']
            numero_serie = request.POST['numero_serie']
            descripcion = request.POST['descripcion']
            nombre_cliente = request.POST['nombre_cliente']
            apellido_cliente = request.POST['apellido_cliente']
            correo_cliente = request.POST['correo_cliente']
            telefono_cliente = request.POST['telefono_cliente']
            id_empleado = request.POST['id_empleado']

            # Validar y convertir la fecha de ingreso
            fecha_ingreso = datetime.strptime(fecha_ingreso, "%Y-%m-%d").date()

            # Llamada a la función PostgreSQL
            with connection.cursor() as cursor:
                cursor.callproc('public.crear_reparacion_completa', [
                    fecha_ingreso, 
                    marca, 
                    modelo, 
                    numero_serie, 
                    descripcion, 
                    nombre_cliente, 
                    apellido_cliente, 
                    correo_cliente, 
                    telefono_cliente, 
                    id_empleado
                ])

            messages.success(request, "✅ Reparación asignada correctamente.")
            return redirect('reparaciones')  # Redirigir a la página de reparaciones

        except Exception as e:
            messages.error(request, f"Error al asignar la reparación: {str(e)}")
            return redirect('asignar')

    # Si no es POST, cargar la página con los empleados
    empleados = Empleado.objects.all()
    return render(request, 'miApp/asignar.html', {'empleados': empleados})


# mas reparaciones
@login_required
def reparaciones(request):
    return render(request, 'miApp/reparaciones.html')

# empleado
@login_required
def perfilempleado(request):
    return render(request, 'miApp/perfilempleado.html', {'empleado': request.user})
