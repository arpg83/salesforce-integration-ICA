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

params = {
    "grant_type": "password",
    "client_id": "3MVG9nSH73I5aFNhduUJOJwAQ5xvrbrj9bo4elwj4u8n4mqORwcU9xdRoQkoYegzIE1USfFAKFv43oX.0irxH", # Consumer Key
    "client_secret": "84E04DA367889884DC4BB33179E99AF7ADDE32CC30C8AD45C548720C2B0D0484", # Consumer Secret
    "username": "userdevelopment3-5f5n@force.com", # The email you use to login
    "password": "Merlin2025SNBbgtUlZe37VluuSTgT8uBEr" # Concat your password and your security token
}

r = requests.post("https://login.salesforce.com/services/oauth2/token", params=params)
# if you connect to a Sandbox, use test.salesforce.com instead
access_token = r.json().get("access_token")
instance_url = r.json().get("instance_url")
print("Access Token: ", access_token)
print("Instance URL: ", instance_url)

logger = logging.getLogger(__name__)
template_env = Environment(loader=FileSystemLoader("templates"))
app = FastAPI()

@app.put("/salesforce/case/attach")
async def attach_file(request: Request) -> OutputModel:
    """
    Endpoint to attach a file to a Salesforce case.

    Args:
        request (Request): The request object containing the file and case information.

    Returns:
        OutputModel: The result of the file attachment operation.
    """

    # Variable con el número de incidente a buscar
    incidente = "00001003"  # Ejemplo de número de CaseNumber

    # Construimos la query filtrando directamente por el número de incidente
    soql = f"SELECT Id, CaseNumber, Subject, Status FROM Case WHERE CaseNumber = '{incidente}' LIMIT 1"
    query_url = f"{instance_url}/services/data/v57.0/query"
    params = {"q": soql}
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(query_url, headers=headers, params=params)
    message_error = None
    invocation_id = str(uuid4())
    response_template = template_env.get_template("response_template_attach_file.jinja")
    if response.status_code == 200:
        data = response.json()
        if data.get("records"):
            encontrado = data["records"][0]
        else:
            encontrado = None
    
        if encontrado:
            print("Incidente encontrado:", encontrado)
    
            # --- Adjuntar archivo al Case encontrado ---
            case_id = encontrado.get("Id")
            print(f"Subiendo archivo al Case con ID: {case_id}")
    
            # Ruta del archivo a subir
            file_path = "C:\\\\proyectos\\\\AWS.pdf"
    
            # Leer y codificar el archivo en Base64
            with open(file_path, "rb") as f:
                file_data = f.read()
                file_base64 = base64.b64encode(file_data).decode("utf-8")
    
            # 1. Subir el archivo como ContentVersion
            content_version_url = f"{instance_url}/services/data/v57.0/sobjects/ContentVersion"
            content_version_payload = {
                "Title": os.path.basename(file_path),
                "PathOnClient": os.path.basename(file_path),
                "VersionData": file_base64
            }
    
            cv_response = requests.post(
                content_version_url,
                headers=headers,
                json=content_version_payload
            )
    
            if cv_response.status_code in (200, 201):
                content_version_id = cv_response.json().get("id")
                print("ContentVersion creado:", content_version_id)
    
                # 2. Consultar el ContentDocumentId asociado
                query_cd_url = f"{instance_url}/services/data/v57.0/query"
                query = f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
                cd_response = requests.get(query_cd_url, headers=headers, params={"q": query})
    
                if cd_response.status_code == 200:
                    content_document_id = cd_response.json()["records"][0]["ContentDocumentId"]
    
                    # 3. Crear el vínculo ContentDocumentLink con el Case
                    cdl_url = f"{instance_url}/services/data/v57.0/sobjects/ContentDocumentLink"
                    cdl_payload = {
                        "ContentDocumentId": content_document_id,
                        "LinkedEntityId": case_id,
                        "ShareType": "V"  # V = View, C = Collaborate
                    }
    
                    cdl_response = requests.post(cdl_url, headers=headers, json=cdl_payload)
    
                    if cdl_response.status_code in (200, 201):
                        print("Archivo adjuntado correctamente al Case con nro. " + incidente)
                        rendered_response = response_template.render(
                            success=True,
                            incident_number=incidente
                        )
                        return OutputModel(
                            status="success",
                            invocationId=invocation_id,
                            response=[ResponseMessageModel(message=rendered_response)]
                        )
                    else:
                        message_error = "Error al crear el ContentDocumentLink"
                        print(message_error, cdl_response.text)
                else:
                    message_error = "Error al obtener ContentDocumentId"
                    print(message_error, cd_response.text)
            else:
                message_error = "Error al crear ContentVersion"
                print(message_error, cv_response.text)
        else:
            message_error = f"No se encontró el incidente {incidente}"
            print(message_error)
    else:
        message_error = "Error"
        print(message_error, response.status_code, response.text)

    message = response_template.render(
    success=False,
    error_message=message_error
    )
    return OutputModel(
        invocationId=invocation_id,
        response=[ResponseMessageModel(message=message)]
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000, log_level="info")
