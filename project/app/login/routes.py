from flask import Blueprint, jsonify, request, send_file
from app.services import upload_to_supabase, download_file_from_supabase, process_file, create_pdf, create_csv, delete_old_files
from app import db
import os
import uuid
import traceback
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename
from app.supabase_client import supabase
import io
import bcrypt
from app import main 

main = Blueprint('main', __name__)


@main.route('/api/register', methods=['POST'])
def register_user():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirm_password')

        if not email or not password or not confirm_password:
            return jsonify({'error': 'Todos los campos son obligatorios.'}), 400

        if password != confirm_password:
            return jsonify({'error': 'Las contraseñas no coinciden.'}), 400

        # Verificar si el correo ya está registrado
        existing_user = supabase.table('users').select('email').eq('email', email).execute()
        if existing_user.data:
            return jsonify({'error': 'El correo ya está registrado.'}), 400

        # Hashear la contraseña
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Insertar en Supabase
        result = supabase.table('users').insert({
            'email': email,
            'password': hashed_password,
            'is_admin': False
        }).execute()

        # Verificar si la inserción fue exitosa
        if result.error:
            return jsonify({'error': 'No se pudo registrar el usuario.'}), 500

        # Obtener el ID del usuario recién creado
        user_id = result.data[0]['id']

        return jsonify({'message': 'Usuario registrado exitosamente.', 'user_id': user_id}), 201

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
