from flask import Blueprint, jsonify, request, current_app, make_response, send_file
from app.services import upload_to_supabase, download_file_from_supabase, process_file, create_pdf, create_csv, delete_old_files
from app import db
import os
import uuid
import traceback
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename
from supabase import create_client
from config.config import Config
import io

supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_API_KEY)


main = Blueprint('main', __name__)

# Carpetas locales (no se modifican)
DOWNLOAD_FOLDER = "downloads"
UPLOAD_FOLDER = "uploads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Limpieza de archivos antiguos
delete_old_files()

    
def consolidate_files(file_paths):
    """
    Lee todos los archivos en file_paths (soportados: CSV y XLSX),
    los concatena en un único DataFrame y lo guarda en un archivo Excel temporal.
    Se usa para consolidar los datos de múltiples archivos.
    """
    dfs = []
    for path in file_paths:
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".xlsx":
                df = pd.read_excel(path, engine="openpyxl")
            elif ext == ".csv":
                # Intentamos leer el CSV de varias maneras
                try:
                    df = pd.read_csv(path, delimiter=",", engine="python")
                except Exception as e:
                    try:
                        df = pd.read_csv(path, delimiter=";", engine="python")
                    except Exception as e:
                        print(f"Error leyendo {path}: {e}")
                        continue
            else:
                continue
            dfs.append(df)
        except Exception as e:
            print(f"Error leyendo {path}: {e}")
            continue
    if not dfs:
        return None, "No se pudo leer ningún archivo válido."
    consolidated_df = pd.concat(dfs, ignore_index=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    consolidated_file = os.path.join(DOWNLOAD_FOLDER, f"{timestamp}_consolidated.xlsx")
    consolidated_df.to_excel(consolidated_file, index=False)
    return consolidated_file, None

@main.route('/api/process-all', methods=['POST'])
def process_all():
    """
    Ruta unificada que:
      - Recibe múltiples archivos y datos del formulario.
      - Sube cada archivo a Supabase y lo registra en la BD.
      - Consolida los datos de todos los archivos en un único archivo Excel.
      - A partir de ese archivo consolidado genera el CSV y el PDF usando las funciones
        create_csv y create_pdf (definidas en services.py) sin alterar su lógica.
      - Sube los archivos generados (CSV y PDF) a Supabase y retorna sus nombres.
    """
    try:
        # Validar campos obligatorios
        user_id = request.form.get('user_id')  # Añadir user_id
        discount_rate = request.form.get('discount_rate')
        
        if not user_id or not discount_rate:
            return jsonify({"error": "user_id y discount_rate son obligatorios."}), 400
        if not discount_rate:
            return jsonify({"error": "discount_rate es obligatorio."}), 400
        try:
            discount_rate = float(discount_rate)
        except ValueError:
            return jsonify({"error": "discount_rate debe ser numérico."}), 400

        # Otros datos del formulario (se usan en el PDF)
        form_data = {
            "purchase_info": request.form.get('purchase_info', ''),
            "order_date": request.form.get('order_date', ''),
            "seller_name": request.form.get('seller_name', ''),
            "seller_PO": request.form.get('seller_PO', ''),
            "seller_address": request.form.get('seller_address', ''),
            "company_name": request.form.get('company_name', ''),
            "company_address": request.form.get('company_address', ''),
            "company_info": request.form.get('company_info', ''),
            "shipping_method": request.form.get('shipping_method', ''),
            "payment_terms": request.form.get('payment_terms', '')
        }

        files = request.files.getlist('files')
        if not files:
            return jsonify({"error": "No se han enviado archivos."}), 400

        allowed_extensions = ['csv', 'xlsx']
        temp_file_paths = []
        errors = []
        # duplicate_files = []
        uploaded_files = []
        renamed_files = []  # Para registrar archivos renombrados

        # Procesar cada archivo recibido
        for file in files:
            if not file:
                continue
            original_filename = file.filename.strip()
            ext = original_filename.split('.')[-1].lower()
            if ext not in allowed_extensions:
                errors.append({"file": original_filename, "error": "Formato no soportado."})
                continue

            # Generar nombre seguro con user_id, timestamp y nombre original
            # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_name = secure_filename(original_filename.rsplit('.', 1)[0])
            # new_filename = f"{timestamp}_{base_name}.{ext}"
            new_filename = f"{base_name}.{ext}"


            
            # Verificar si el nombre ya existe en la base de datos
           

            temp_path = os.path.join(UPLOAD_FOLDER, new_filename)
            file.save(temp_path)
            temp_file_paths.append(temp_path)

            # Subir a Supabase y registrar en la BD
            supa_path = f"xlsx/{user_id}/{new_filename}"  # Cambiar esta línea
            if upload_to_supabase(temp_path, supa_path) is None:
                errors.append({"file": original_filename, "error": "Error al subir a Supabase."})
                os.remove(temp_path)
                continue

           
            uploaded_files.append({
                'original_name': original_filename,  # Guardamos el original solo en la respuesta
                'stored_name': new_filename
            })
        
      

        if not temp_file_paths:
            return jsonify({"error": "No se pudo procesar ningún archivo válido.", "details": errors}), 400

        # Consolidar todos los archivos en uno solo
        consolidated_file, consolidate_error = consolidate_files(temp_file_paths)
        if consolidate_error:
            return jsonify({"error": consolidate_error}), 500

        # Generar el CSV consolidado
        # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        excel_base = secure_filename(files[0].filename.rsplit('.', 1)[0])
        csv_filename = f"{excel_base}.csv"
        csv_path = os.path.join(DOWNLOAD_FOLDER, csv_filename)
        csv_result = create_csv(consolidated_file, csv_path)
        if "error" in csv_result:
            return jsonify(csv_result), 500

        # Generar el PDF consolidado
        pdf_filename = f"{excel_base}.pdf"
        pdf_path = os.path.join(DOWNLOAD_FOLDER, pdf_filename)
        pdf_result = create_pdf(consolidated_file, pdf_path, discount_rate, form_data)
        if "error" in pdf_result:
            return jsonify(pdf_result), 500

        # Subir CSV y PDF a Supabase
        upload_to_supabase(csv_path, f"csv/{user_id}/{csv_filename}")
        upload_to_supabase(pdf_path, f"pdf/{user_id}/{pdf_filename}")

        # Limpiar archivos temporales (archivos individuales y el consolidado)
        for path in temp_file_paths:
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(consolidated_file):
            os.remove(consolidated_file)

        return jsonify({
            "message": "Procesamiento completado exitosamente.",
            "download_links": {
                "csv": f"/download/csv?user_id={user_id}&filename={csv_filename}",
                "pdf": f"/download/pdf?user_id={user_id}&filename={pdf_filename}"
            },
            "uploaded_files": uploaded_files,
            "renamed_files": renamed_files,  # Informar sobre archivos renombrados
            "csv": csv_filename,
            "pdf": pdf_filename,
            "errors": errors
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@main.route('/api/files', methods=['GET'])
def list_files():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "El parámetro user_id es requerido"}), 400

        bucket_name = 'uploads'  # Confirmado que tu bucket se llama 'uploads'
        tipos_archivos = ['pdf', 'csv', 'xlsx']
        archivos = []

        for tipo in tipos_archivos:
            try:
                # Construir la ruta correcta: tipo/user_id/
                carpeta = f"{tipo}/{user_id}"
                
                # Listar archivos en Supabase
                response = supabase.storage.from_(bucket_name).list(carpeta)
                
                if not response:
                    print(f"No se encontraron archivos en {carpeta}")
                    continue
                
                for file_info in response:
                    if not file_info.get('name') or file_info['name'].startswith('.'):
                        continue
                    
                    nombre_archivo = file_info['name']
                    file_path = f"{carpeta}/{nombre_archivo}"
                    
                    try:
                        # Obtener URL pública (asegúrate que los archivos son públicos)
                        url_descarga = supabase.storage.from_(bucket_name).get_public_url(file_path)
                        
                        archivos.append({
                            "nombre": nombre_archivo,
                            "tipo": tipo,
                            "fecha_subida": file_info.get('created_at', datetime.now().isoformat()),
                            "tamano": file_info.get('metadata', {}).get('size', 0),
                            "url": url_descarga
                        })
                    except Exception as e:
                        print(f"Error al obtener URL para {file_path}: {str(e)}")
                        continue
                    
            except Exception as e:
                print(f"Error al listar {tipo}: {str(e)}")
                continue

        return jsonify({
            "success": True,
            "archivos": archivos
        }), 200

    except Exception as e:
        print(f"Error general: {str(e)}")
        return jsonify({
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500

@main.route('/download/<tipo>', methods=['GET'])
def descargar_archivo(tipo):
    try:
        user_id = request.args.get('user_id')
        filename = request.args.get('filename')

        if not all([user_id, filename]):
            return jsonify({
                "error": "Parámetros faltantes",
                "requeridos": ["user_id", "filename"]
            }), 400

        # Validar tipo de archivo
        valid_types = ['pdf', 'csv', 'xlsx']
        if tipo not in valid_types:
            return jsonify({
                "error": "Tipo de archivo no válido",
                "tipos_aceptados": valid_types
            }), 400

        # Validar nombre de archivo para seguridad
        if not secure_filename(filename) == filename:
            return jsonify({"error": "Nombre de archivo no válido"}), 400

        # Construir ruta en Supabase
        file_path = f"{tipo}/{user_id}/{filename}"
        bucket_name = 'uploads'

        try:
            # Descargar el archivo desde Supabase
            file_data = supabase.storage.from_(bucket_name).download(file_path)
            
            if not file_data:
                return jsonify({"error": "Archivo no encontrado"}), 404

            # Crear respuesta
            response = make_response(file_data)
            
            # Configurar headers según tipo de archivo
            if tipo == 'pdf':
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            elif tipo == 'csv':
                response.headers['Content-Type'] = 'text/csv'
                response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            else:  # xlsx
                response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response

        except Exception as download_error:
            current_app.logger.error(f"Error al descargar: {str(download_error)}")
            return jsonify({
                "error": "No se pudo descargar el archivo",
                "details": str(download_error)
            }), 500

    except Exception as e:
        current_app.logger.error(f"Error en descarga: {str(e)}")
        return jsonify({
            "error": "Error interno al procesar la solicitud",
            "details": str(e)
        }), 500