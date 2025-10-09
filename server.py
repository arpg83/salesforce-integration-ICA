import requests
import urllib.parse
import base64
import os
import logging
import uvicorn
from uuid import uuid4
from jinja2 import Environment, FileSystemLoader
from fastapi import FastAPI, Request
from schemas import ResponseMessageModel, OutputModel
from dotenv import load_dotenv
from simple_salesforce import Salesforce
import re

load_dotenv()

username = os.getenv("SALESFORCE_USER_NAME")
password = os.getenv("SALESFORCE_PASSWORD")
security_token = os.getenv("SALESFORCE_SECURITY_TOKEN")
domain = os.getenv("SALESFORCE_DOMAIN")  # "login" o "test"

try:
    client = Salesforce(
        username=username,
        password=password,
        security_token=security_token,
        domain=domain
    )
    print("✅ Conectado a Salesforce correctamente")
    print("Instancia:", client.sf_instance)
except Exception as e:
    print("❌ Error al conectar con Salesforce:", e)

logger = logging.getLogger(__name__)
template_env = Environment(loader=FileSystemLoader("templates"))
app = FastAPI()


@app.put("/salesforce/case/attach")
async def attach_file(request: Request) -> OutputModel:
    """
    Endpoint para adjuntar un archivo a un caso de Salesforce.
    """
    data = await request.json()
    incidente = data.get("incidente")
    file_url = data.get("url_file")
    invocation_id = str(uuid4())

    # Ajustar URLs (Drive, Dropbox, OneDrive)
    if "drive.google.com" in file_url:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", file_url)
        if match:
            file_id = match.group(1)
            file_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    if "dropbox.com" in file_url:
        file_url = file_url.replace("?dl=0", "?dl=1")

    if "sharepoint.com" in file_url or "1drv.ms" in file_url:
        if "download=1" not in file_url:
            file_url += "&download=1" if "?" in file_url else "?download=1"

    response_template = template_env.get_template("response_template_attach_file.jinja")

    try:
        # Buscar el caso por número
        soql = f"SELECT Id, CaseNumber FROM Case WHERE CaseNumber = '{incidente}' LIMIT 1"
        result = client.query(soql)

        if not result["records"]:
            message_error = f"No se encontró el incidente {incidente}"
            message = response_template.render(success=False, error_message=message_error)
            return OutputModel(invocationId=invocation_id, response=[ResponseMessageModel(message=message)])

        case_id = result["records"][0]["Id"]
        print(f"Case encontrado: {case_id}")

        # Descargar archivo
        file_response = requests.get(file_url)
        if file_response.status_code != 200:
            message_error = f"No se pudo descargar el archivo desde la URL (Código {file_response.status_code})"
            message = response_template.render(success=False, error_message=message_error)
            return OutputModel(invocationId=invocation_id, response=[ResponseMessageModel(message=message)])

        file_data = file_response.content
        file_base64 = base64.b64encode(file_data).decode("utf-8")
        file_name = os.path.basename(file_url.split("?")[0]) or "archivo.pdf"

        # Crear ContentVersion
        content_version = client.ContentVersion.create({
            "Title": file_name,
            "PathOnClient": file_name,
            "VersionData": file_base64
        })
        content_version_id = content_version.get("id")
        print("ContentVersion creado:", content_version_id)

        # Obtener ContentDocumentId
        query_cd = f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
        cd_result = client.query(query_cd)
        content_document_id = cd_result["records"][0]["ContentDocumentId"]

        # Crear vínculo ContentDocumentLink con el Case
        client.ContentDocumentLink.create({
            "ContentDocumentId": content_document_id,
            "LinkedEntityId": case_id,
            "ShareType": "V"
        })

        print("Archivo adjuntado correctamente al Case:", incidente)
        rendered_response = response_template.render(success=True, incident_number=incidente)
        return OutputModel(
            status="success",
            invocationId=invocation_id,
            response=[ResponseMessageModel(message=rendered_response)]
        )

    except Exception as e:
        message_error = f"Error al adjuntar archivo: {e}"
        print(message_error)
        message = response_template.render(success=False, error_message=message_error)
        return OutputModel(invocationId=invocation_id, response=[ResponseMessageModel(message=message)])

@app.put("/salesforce/case/update")
async def update_state(request: Request) -> OutputModel:
    """
    Endpoint para actualizar el estado de un caso de Salesforce.
    """
    data = await request.json()
    incidente = data.get("incidente")
    nuevo_estado = data.get("nuevo_estado")

    invocation_id = str(uuid4())
    response_template = template_env.get_template("response_template_case_update.jinja")

    try:
        # Buscar el caso por número
        soql = f"SELECT Id, CaseNumber, Subject, Status FROM Case WHERE CaseNumber = '{incidente}' LIMIT 1"
        result = client.query(soql)

        if not result["records"]:
            message_error = f"No se encontró el incidente {incidente}"
            message = response_template.render(success=False, error_message=message_error)
            return OutputModel(invocationId=invocation_id, response=[ResponseMessageModel(message=message)])

        case_id = result["records"][0]["Id"]
        print(f"Caso encontrado: {case_id}")

        # Actualizar estado del caso
        client.Case.update(case_id, {"Status": nuevo_estado})
        print(f"Estado actualizado a '{nuevo_estado}' para el caso {incidente}")

        rendered_response = response_template.render(success=True, incident_number=incidente)
        return OutputModel(
            status="success",
            invocationId=invocation_id,
            response=[ResponseMessageModel(message=rendered_response)]
        )

    except Exception as e:
        message_error = f"Error al actualizar estado: {e}"
        print(message_error)
        message = response_template.render(success=False, error_message=message_error)
        return OutputModel(invocationId=invocation_id, response=[ResponseMessageModel(message=message)])

@app.get("/salesforce/case/list")
async def list_incidents(request: Request) -> OutputModel:
    """
    Listar casos desde Salesforce filtrados por estado.
    """
    data = await request.json()
    status = data.get("status")

    invocation_id = str(uuid4())
    response_template = template_env.get_template("response_template_incidents.jinja")

    try:
        # Consulta SOQL
        soql = f"SELECT Id, CaseNumber, Subject, Status FROM Case WHERE Status = '{status}'"
        result = client.query(soql)
        incidents = result.get("records", [])
        count = len(incidents)

        rendered_response = (
            response_template.render(count=count, incidents=incidents)
            if count > 0
            else "No se encontraron incidentes"
        )

        return OutputModel(
            invocationId=invocation_id,
            response=[ResponseMessageModel(message=rendered_response)]
        )

    except Exception as e:
        logger.error(f"Error al obtener incidentes: {e}")
        return OutputModel(
            invocationId=invocation_id,
            response=[ResponseMessageModel(message=f"Error al obtener incidentes para el estado: {status}")]
        )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000, log_level="info")
