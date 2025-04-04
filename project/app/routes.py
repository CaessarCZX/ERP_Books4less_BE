from flask import Blueprint, jsonify, request, send_file
from app.services import upload_to_supabase, download_file_from_supabase, process_file, create_pdf, create_csv, delete_old_files
from app import db
from app.models import UserFiles
import os
import uuid
import traceback
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename

main = Blueprint('main', __name__)

# Carpetas locales (no se modifican)
DOWNLOAD_FOLDER = "downloads"
UPLOAD_FOLDER = "uploads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Limpieza de archivos antiguos
delete_old_files()
@main.route('/api/user-files', methods=['GET'])
def get_user_files():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400
    
    # Filtros adicionales
    file_type = request.args.get('file_type')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    
    try:
        query = UserFiles.query.filter_by(user_id=user_id)
        
        if file_type:
            query = query.filter(UserFiles.file_type.ilike(f"%{file_type}%"))
        
        if from_date:
            query = query.filter(UserFiles.uploaded_at >= from_date)
            
        if to_date:
            query = query.filter(UserFiles.uploaded_at <= to_date)
        
        files = query.order_by(UserFiles.uploaded_at.desc()).all()
        
        files_data = [{
            'id': file.id,
            'filename': file.filename,
            'uploaded_at': file.uploaded_at.isoformat() if file.uploaded_at else None,
            'file_type': file.file_type
        } for file in files]
        
        return jsonify({'files': files_data})
    except Exception as e:
        current_app.logger.error(f"Error getting user files: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@main.route('/download/pdf', methods=['GET'])
def download_pdf():
    """
    Endpoint para descargar un PDF subido.
    Se espera recibir el parámetro 'filename' en la query string.
    Ejemplo: /download/pdf?filename=1234_20250403_131200_output.pdf
    """
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"error": "Parámetro 'filename' no proporcionado."}), 400

    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        # También se puede intentar descargar desde Supabase si el archivo no está local
        download_result = download_file_from_supabase(f"pdf/{filename}")
        if isinstance(download_result, dict) and "error" in download_result:
            return jsonify(download_result), 500
        file_path = download_result

    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main.route('/download/csv', methods=['GET'])
def download_csv():
    """
    Endpoint para descargar un CSV subido.
    Se espera recibir el parámetro 'filename' en la query string.
    Ejemplo: /download/csv?filename=1234_20250403_131200_output.csv
    """
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"error": "Parámetro 'filename' no proporcionado."}), 400

    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        # También se puede intentar descargar desde Supabase si el archivo no está local
        download_result = download_file_from_supabase(f"csv/{filename}")
        if isinstance(download_result, dict) and "error" in download_result:
            return jsonify(download_result), 500
        file_path = download_result

    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    
def consolidate_files(file_paths, user_id):
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
    consolidated_file = os.path.join(DOWNLOAD_FOLDER, f"{user_id}_consolidated.xlsx")
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
        user_id = request.form.get('user_id')
        discount_rate = request.form.get('discount_rate')
        if not user_id or not discount_rate:
            return jsonify({"error": "user_id y discount_rate son obligatorios."}), 400
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
        duplicate_files = []
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
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_name = secure_filename(original_filename.rsplit('.', 1)[0])
            new_filename = f"{user_id}_{timestamp}_{base_name}.{ext}"
            
            # Verificar si el nombre ya existe en la base de datos
            existing_file = UserFiles.query.filter_by(filename=new_filename).first()
            if existing_file:
                # Si existe, agregar un sufijo único
                unique_suffix = uuid.uuid4().hex[:4]
                new_filename = f"{user_id}_{timestamp}_{base_name}_{unique_suffix}.{ext}"
                renamed_files.append({
                    'original': original_filename,
                    'new': new_filename,
                    'reason': 'El archivo ya existía en el sistema'
                })

            temp_path = os.path.join(UPLOAD_FOLDER, new_filename)
            file.save(temp_path)
            temp_file_paths.append(temp_path)

            # Subir a Supabase y registrar en la BD
            supa_path = f"uploads/{user_id}/{new_filename}"
            if upload_to_supabase(temp_path, supa_path) is None:
                errors.append({"file": original_filename, "error": "Error al subir a Supabase."})
                os.remove(temp_path)
                continue

            # Crear registro sin el campo original_name
            new_file = UserFiles(
                user_id=user_id,
                filename=new_filename,  # Usamos el nuevo nombre generado
                file_type=ext,
                file_path=temp_path
            )
            db.session.add(new_file)
            uploaded_files.append({
                'original_name': original_filename,  # Guardamos el original solo en la respuesta
                'stored_name': new_filename
            })
        
        db.session.commit()

        if not temp_file_paths:
            return jsonify({"error": "No se pudo procesar ningún archivo válido.", "details": errors}), 400

        # Consolidar todos los archivos en uno solo
        consolidated_file, consolidate_error = consolidate_files(temp_file_paths, user_id)
        if consolidate_error:
            return jsonify({"error": consolidate_error}), 500

        # Generar el CSV consolidado
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_filename = f"{user_id}_{timestamp}_output.csv"
        csv_path = os.path.join(DOWNLOAD_FOLDER, csv_filename)
        csv_result = create_csv(consolidated_file, csv_path)
        if "error" in csv_result:
            return jsonify(csv_result), 500

        # Generar el PDF consolidado
        pdf_filename = f"{user_id}_{timestamp}_output.pdf"
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
            "uploaded_files": uploaded_files,
            "renamed_files": renamed_files,  # Informar sobre archivos renombrados
            "csv": csv_filename,
            "pdf": pdf_filename,
            "errors": errors
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500