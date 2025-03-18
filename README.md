# 📚 ERP_Books4less_BE — Sistema de gestión de inventario con Flask y Supabase  


## 🚀 **Instalación y configuración**  

### 1️⃣ **Clonar el repositorio**  
Clona este repositorio en tu máquina local:  
```bash
git clone https://github.com/CaessarCZX/ERP_Books4less_BE.git
```
### 2️⃣ **Crear entorno virtual** 
```bash
python -m venv venv
```
### 3️⃣ Activar entorno virtual
Para activar el entorno virtual, usa el siguiente comando según tu sistema operativo:
Windows:
```bash
.\venv\Scripts\activate
```
Linux/macOS:
```bash
source venv/bin/activate
```
Si la activación fue exitosa, deberías ver algo como esto en la terminal:

```bash
(venv) C:\Users\Mario Ramón\8to semestre\Backend-chamba2>
```
### 4️⃣ Instalar dependencias
Instala las dependencias del proyecto desde el archivo requirements.txt:
```bash
pip install -r requirements.txt
```
⚠️ Nota: Si tienes problemas con las dependencias, prueba actualizando pip primero:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
### 5️⃣ Configurar las credenciales de Supabase
Crea un archivo .env en la raíz del proyecto y agrega las siguientes credenciales de Supabase:
```bash
SUPABASE_URL= 
SUPABASE_API_KEY=
```
⚠️ ⚠️ Nota: No compartas este archivo .env públicamente ni lo subas al repositorio. Estas crendeciales las puse en trello

## 🏗️ **Estructura del proyecto**  
| Archivo/Carpeta | Propósito |
|-----------------|-----------|
| `app/__init__.py` | Inicializa la aplicación Flask y la configuración de la base de datos. |
| `app/models.py` | Define las clases y modelos usando SQLAlchemy. |
| `app/routes.py` | Define las rutas y la lógica para la API y las vistas. |
| `app/templates/` | Contiene las plantillas HTML para las vistas. |
| `app/static/` | Contiene los archivos estáticos (CSS y JS). |
| `.env` | Almacena las credenciales de Supabase de manera segura. |
| `config.py` | Configura la conexión con la base de datos y otras opciones de Flask. |
| `requirements.txt` | Lista las dependencias del proyecto para instalar con `pip`. |
| `run.py` | Archivo para arrancar el servidor Flask. |

---

🌟 **¿Por qué esta estructura es mejor?**  
✔️ Organizada por módulos, facilitando la escalabilidad y mantenimiento.  
✔️ Sigue el patrón MVC (Modelo-Vista-Controlador), lo que ayuda a mantener una estructura clara y ordenada.  
✔️ Archivos estáticos y plantillas HTML organizados en carpetas separadas para mayor claridad.  

### 🚦 Ejecutar el proyecto
Para iniciar la aplicación Flask, ejecuta el siguiente comando:
``` bash
python run.py
```
### ✅ Verificar la conexión a Supabase
Para comprobar que la conexión a Supabase está funcionando correctamente, abre tu navegador y visita:
👉 http://127.0.0.1:5000/check_connection

Si la conexión es exitosa, debería devolver una respuesta JSON similar a esta:
``` bash
{
  "message": "Conexión exitosa a Supabase",
  "data": [...]
}
```
### 🛠️ Comandos útiles
| Comando | Descripción |
|---------|-----------|
|`git status`| Muestra el estado de los archivos en el repositorio.|
|`git add .`	| Añade todos los cambios al área de preparación.|
|`git commit` | -m "mensaje"	Guarda los cambios en el repositorio local.|
|`git push`	| Sube los cambios al repositorio remoto.|
|`git pull`	| Descarga los cambios del repositorio remoto.|

### 🌟 Tecnologías usadas
✅ Flask

✅ Flask-SQLAlchemy

✅ Flask-Cors

✅ psycopg2

✅ python-dotenv

✅ Supabase

✅ pandas

✅ numpy

### 💡 Consejos
Si tienes problemas con las dependencias, prueba actualizando pip y reinstalando las dependencias:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
### 🎯 Contribuir
Si deseas contribuir:

1. Haz un fork del repositorio.
2. Crea una nueva rama para tus cambios.
3. Realiza un commit claro y descriptivo.
4. Envía un pull request para revisión.
   
¡Cualquier ayuda es bienvenida! 😎

### 👤 Autor
Mario Juan Ramón Morales
👉 GitHub
👉 LinkedIn
