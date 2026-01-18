import json
from openai import OpenAI
import pdfplumber
from pydantic import BaseModel
import gradio as gr
from alerts import *
from config import *

def is_over_budget(ip: str) -> bool:
    return token_usage[ip] >= MAX_TOKENS_PER_IP

def estimate_tokens(text: str) -> int:
    # ~1 token cada 4 caracteres (regla empírica)
    return max(1, len(text) // 4)

def register_token_usage(ip: str, texts: list[str]):
    total = sum(estimate_tokens(t) for t in texts)
    token_usage[ip] += total
    return token_usage[ip]

abuse_notified = set()

if not EMAIL_ALERTS_ENABLED:
    print("⚠️Alertas por email desactivadas.")

openai_client = OpenAI()

gemini = OpenAI(
    api_key=os.getenv("GOOGLE_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

perplexity = OpenAI(
    api_key=os.getenv("PERPLEXITY_API_KEY"),
    base_url="https://api.perplexity.ai"
)

profile = ""
with pdfplumber.open("profile.pdf") as pdf:
    for page in pdf.pages:
        profile += page.extract_text() or ""
profile = profile.replace("MMAANNGGOO", "MANGO")

with open("resume.txt", "r", encoding="utf-8") as f:
    resume = f.read()

name = "Miguel de la Ossa Abellán"
system_prompt = f"""Estás actuando como {name}. Estás respondiendo a preguntas en el sitio web de {name}, 
particularment preguntas relacionadas con la carrera, antecedentes, habilidades y experiencia de {name}. 
Tu responsabilidad es representar a {name} para las interacciones en el sitio web de la manera más fiel posible. 
Se te proporciona un resumen de los antecedentes de {name} y el perfil que puedes usar para responder preguntas.
Ten en cuenta que se han añadido proyectos en {resume} que no figuran en {profile}, pero que lo complementan.

INSTRUCCIONES IMPORTANTES: 
-Sé profesional y atractivo, como si hablaras con un cliente potencial o futuro empleador que se encontró con el sitio web.
-No contestes a preguntas no relacionadas con tu perfil. Simplemente, ignóralas.
-Si el usuario muestra interés en contactarte con una propuesta laboral, pide su email y regístralo usando 
la herramienta 'register_proposal', pero no preguntes por detalles adicionales. Simplemente, informa que registraste
la propuesta.
-Responde en el idioma en el que te pregunten. 
-Si no sabes la respuesta, dilo.

## Resumen:
{resume}

## Perfil de LinedIn:
{profile}

Con este contexto, por favor chatea con el usuario, manteniéndote siempre en el personaje de {name}."""

def safe_openai_chat(model, messages, tools, context=None):
    try:
        finished = False
        response = {}
        while not finished:
            response = openai_client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
            )
            end_reason = response.choices[0].finish_reason
            if end_reason == "tool_calls":
                ia_message = response.choices[0].message
                tool_calls = ia_message.tool_calls
                results = manage_tools(tool_calls)
                messages.append(ia_message)
                messages.extend(results)
            else:
                finished = True

        if not response.choices:
            raise ValueError("Respuesta sin choices")

        return response.choices[0].message.content

    except Exception as e:
        send_error_email(
            subject="Error OpenAI - CV Assistant",
            error=e,
            context={
                "model": model,
                "messages": messages,
                "extra": context
            }
        )
        raise

def safe_perplexity_evaluate(messages):
    try:
        response = perplexity.chat.completions.parse(
            model="sonar",
            messages=messages,
            response_format=Evaluation
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Parsing Perplexity devolvió None")

        return parsed

    except Exception as e:
        send_error_email(
            subject="Error Perplexity Evaluation - CV Assistant",
            error=e,
            context={"messages": messages}
        )
        raise

def register_proposal(email, name="No proporcionado", details="No proporcionados"):
    proposal = f"Contacto {name} con email {email} con propuesta: {details}"
    print(proposal)
    send_email(proposal)
    return {"register": "success"}

register_proposal_tool = {
    "name" : "register_proposal",
    "description": "Usa esta herramienta cuando un usuario quiera enviar una propuesta y proporciona su email",
    "parameters": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Dirección de email del usuario"
                },
                "name": {
                    "type": "string",
                    "description": "Nombre del usuario, si lo proporcionó"
                },
                "details": {
                    "type": "string",
                    "description": "Detalles de la propuesta, si los proporcionó"
                }
            },
            "required": ["email"],
            "additionalProperties": False
    }
}

registered_tools = [
    {"type": "function", "function": register_proposal_tool}
]

def manage_tools(tool_calls):
    results = []
    for call in tool_calls:
        tool_name = call.function.name
        args = json.loads(call.function.arguments)
        print(f"Ejecutando herramienta {tool_name}", flush=True)
        result = {}
        if tool_name == "register_proposal":
            result = register_proposal(**args)
        else:
            result = {"error": "Herramienta no existe"}
        results.append({
            "role": "tool",
            "content": json.dumps(result),
            "tool_call_id": call.id
        })
    return results

def notify_abuse(event, ip, message, usage):
    send_error_email(
        subject=f"Abuso detectado: {event}",
        error=Exception(event),
        context={
            "ip": ip,
            "message": message,
            "token_usage": usage
        }
    )

class Evaluation(BaseModel):
    is_acceptable: bool
    retroalimentation: str

prompt_evaluation_system = f"""Eres un evaluador que decide si una respuesta a una pregunta es aceptable.
Se te proporciona una conversación entre un usuario y un agente. Tu tarea es decidir si la última
respuesta del agente es de calidad aceptable.
El agente está interpretando del papel de {name} y está representando a {name} en su sitio web.
Se ha instruído al agente para que sea profesional y atractivo, como si hablara con un cliente potencial
o futuro empleador que se encontró con el sitio web.
Pero debes asegurarte de que no inventa nada que no esté en el resumen ni en los detalles de LinkedIn;
controla que el agente no cree detalles inexistentes.
Si el agente acepta una propuesta, acepta la respuesta de forma incondicional.
Se ha proporcionado al agente el contexto sobre {name} en forma de su resumen y detalles en LinkedIn.
Aquí está la información:

## Resumen:
{resume}

## Perfil de LinkedIn:
{profile}

Con este contexto, por favor evalúa la última respuesta, respondiendo si la respuesta
es aceptable y tu retroalimentación."""

def prompt_evaluator_user(answer, message, history):
    user_prompt = f"Aquí está la conversación entre el usuario y el agente:\n\n{history}\n\n"
    user_prompt += f"Aquí está el último mensaje del usuario:\n\n{message}\n\n"
    user_prompt += f"Aquí está la última respuesta del agente:\n\n{answer}\n\n"
    user_prompt += f"Por favor, evalúa la respuesta, respondiendo si es aceptable y tu retroalimentación."
    return user_prompt

def evaluate(answer, message, history) -> Evaluation:
    messages = [{"role": "system", "content": prompt_evaluation_system}] + [{"role": "user", "content": prompt_evaluator_user(answer, message, history)}]
    #answer_eval = gemini.beta.chat.completions.parse(model="gemini-flash-latest", messages=messages, response_format=Evaluation)
    return safe_perplexity_evaluate(messages)

def rexecute(answer, message, history, retroalimentation):
    system_prompt_updated = system_prompt + "\n\n## Respuesta anterior rechazada." + \
        "\nAcabas de intentar responder, pero el control de calidad rechazó tu respuesta.\n"
    system_prompt_updated += f"## Tu respuesta intentada:\n{answer}\n\n"
    system_prompt_updated += f"## Razón del rechazo:\n{retroalimentation}\n\n"
    print(f"{retroalimentation}")
    messages = [{"role": "system", "content": system_prompt_updated}] + history + [{"role": "user", "content": message}]
    new_answer = openai_client.chat.completions.create(model="o4-mini", messages=messages)
    return new_answer.choices[0].message.content

def chatting(message, history, request: gr.Request | None = None):
    ip = "unknown"

    if request and request.client:
        ip = request.client.host

    # 1️⃣ ¿Presupuesto agotado?
    if is_over_budget(ip):

        if ip not in abuse_notified:
            notify_abuse(
                event="Presupuesto de tokens agotado",
                ip=ip,
                message=message,
                usage=token_usage[ip]
            )
            abuse_notified.add(ip)

        return (
            "Has alcanzado el límite de uso para esta sesión."
            "Si deseas continuar, contáctame en otro momento."
        )

    # 2️⃣ Registrar input del usuario
    register_token_usage(ip, [message])

    try:
        if not history:
            return safe_openai_chat(
                model="o4-mini",
                messages=[{"role": "system", "content": system_prompt}],
                tools=registered_tools,
                context={"phase": "intro"}
            )

        messages = [{"role": "system", "content": system_prompt}] + history + [
            {"role": "user", "content": message}
        ]
        chat_response = safe_openai_chat(
            model="o4-mini",
            messages=messages,
            tools=registered_tools,
            context={"phase": "answer"}
        )

        evaluation = evaluate(chat_response, message, history)

        if not evaluation.is_acceptable:
            print("Falló la evaluación - reintentando")
            chat_response = rexecute(
                chat_response,
                message,
                history,
                evaluation.retroalimentation
            )
        else:
            print("Pasó la evaluación - devolviendo respuesta")

        return chat_response

    except Exception as e:
        # UX controlada
        send_error_email(
            subject=f"Error técnico: {e}",
            error=e,
            context={
                "ip": ip,
                "message": "Lo siento, en este momento se ha producido un problema técnico. "
            }
        )
        return (
            "Lo siento, en este momento se ha producido un problema técnico. "
            "He sido notificado automáticamente y lo revisaré en breve."
        )

intro = (f"Hola, soy {name}, desarrollador de software especializado en COBOL y soluciones multiplataforma. ¿En qué puedo ayudarte hoy?\n\n" +
         f"Hello, I'm {name}, a software developer specialized in COBOL and multi-platform solutions. How can I help you today?")

chatbot = gr.Chatbot(
    value=[{"role": "assistant", "content": intro}],
    height=500,
)

gr.ChatInterface(
    fn=chatting,
    chatbot=chatbot,
    title=f"Asistente del currículum de {name}"
).queue().launch(server_name="0.0.0.0", server_port=7860)

