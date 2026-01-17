from collections import defaultdict

from dotenv import load_dotenv
from numpy.f2py.auxfuncs import throw_error
from openai import OpenAI
import pdfplumber
from pydantic import BaseModel
import gradio as gr
from alerts import *
from config import EMAIL_ALERTS_ENABLED

MAX_TOKENS_PER_IP = 5_000
token_usage = defaultdict(int)

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

load_dotenv(override=True)

if not EMAIL_ALERTS_ENABLED:
    print("⚠️Alertas por email desactivadas.")

openai_client = OpenAI()

gemini = OpenAI(
    api_key=os.getenv("GOOGLE_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

profile = ""
with pdfplumber.open("profile.pdf") as pdf:
    for page in pdf.pages:
        profile += page.extract_text() or ""
profile = profile.replace("MMAANNGGOO", "MANGO")

#print(profile)

with open("resume.txt", "r", encoding="utf-8") as f:
    resume = f.read()

#print(resume)

name = "Miguel de la Ossa Abellán"
system_prompt = (f"Estás actuando como {name}. Estás respondiendo a preguntas en el sitio web de {name}, " +
    "particularment preguntas relacionadas con la carrera, antecedentes, habilidades y experiencia de {name}. " +
    "Tu responsabilidad es representar a {name} para las interacciones en el sitio web de la manera más fiel posible. " +
    "Se te proporciona un resumen de los antecedentes de {name} y el perfil que puedes usar para responder preguntas. " +
    "Sé profesional y atractivo, como si hablaras con un cliente potencial o futuro empleador que se encontró con el sitio web. " +
    "Si te preguntan en inglés, contesta en inglés. Si lo hacen en español, contesta en español. " +
    "Si no sabes la respuesta, dilo. ")

system_prompt += f"\n\n## Resumen:\n{resume}\n\n## Perfil de LinedIn:\n{profile}\n\n"
system_prompt += f"Con este contexto, por favor chatea con el usuario, manteniéndote siempre en el personaje de {name}."

#print(system_prompt)

def safe_openai_chat(model, messages, context=None):
    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=messages
        )

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

def safe_gemini_evaluate(messages):
    try:
        response = gemini.beta.chat.completions.parse(
            model="gemini-flash-latest",
            messages=messages,
            response_format=Evaluation
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Parsing Gemini devolvió None")

        return parsed

    except Exception as e:
        send_error_email(
            subject="Error Gemini Evaluation - CV Assistant",
            error=e,
            context={"messages": messages}
        )
        raise

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

prompt_evaluation_system = f"Eres un evaluador que decide si una respuesta a una pregunta es aceptable. " + \
    "Se te proporciona una conversación entre un usuario y un agente. Tu tarea es decidir si la última " + \
    "respuesta del agente es de calidad aceptable." + \
    "El agente está interpretando del papel de {name} y está representando a {name} en su sitio web. " + \
    "Se ha instruido al agente para que sea profesional y atractivo, como si hablara con un cliente potencial " + \
    "o futuro empleador que se encontró con el sitio web. " + \
    "Pero debes asegurarte de que no inventa nada que no esté en su resumen ni en los detalles de LinkedIn; " + \
    "controla que el agente no cree detalles inexistentes. " + \
    "Tampoco aceptes ninguna propuesta de trabajo. En ese caso, invita al posible empleador a enviar un " + \
    "email a la dirección que figura en el perfil de LinkedIn o en el currículum. " + \
    "Se ha proporcionado al agente el contexto sobre {name} en forma de su resumen y detalles en LinkedIn. " + \
    "Aquí está la información:"

prompt_evaluation_system += f"\n\n## Resumen:\n{resume}\n\n## Perfil de LinedIn:\n{profile}\n\n"
prompt_evaluation_system += f"Con este contexto, por favor evalúa la última respuesta, respondiendo si la respuesta " + \
    "es aceptable y tu retroalimentación."

# print(prompt_evaluation_system)

def prompt_evaluator_user(answer, message, history):
    user_prompt = f"Aquí está la conversación entre el usuario y el agente:\n\n{history}\n\n"
    user_prompt += f"Aquí está el último mensaje del usuario:\n\n{message}\n\n"
    user_prompt += f"Aquí está la última respuesta del agente:\n\n{answer}\n\n"
    user_prompt += f"Por favor, evalúa la respuesta, respondiendo si es aceptable y tu retroalimentación."
    return user_prompt

def evaluate(answer, message, history) -> Evaluation:
    messages = [{"role": "system", "content": prompt_evaluation_system}] + [{"role": "user", "content": prompt_evaluator_user(answer, message, history)}]
    #answer_eval = gemini.beta.chat.completions.parse(model="gemini-flash-latest", messages=messages, response_format=Evaluation)
    return safe_gemini_evaluate(messages)

# question = "¿Qué idiomas manejas?"
# messages = [{"role": "system", "content": system_prompt}] + [{"role": "user", "content": question}]
# answer = openai_client.chat.completions.create(model="o4-mini", messages=messages)
# chat_response = answer.choices[0].message.content
#
# print(chat_response)

# print(evaluate(chat_response, question, messages[:1]))

def rexecute(answer, message, history, retroalimentation):
    system_prompt_updated = system_prompt + "\n\n## Respuesta anterior rechazada." + \
        "\nAcabas de intentar responder, pero el control de calidad rechazó tu respuesta.\n"
    system_prompt_updated += f"## Tu respuesta intentada:\n{answer}\n\n"
    system_prompt_updated += f"## Razón del rechazo:\n{retroalimentation}\n\n"
    print(f"{retroalimentation}")
    messages = [{"role": "system", "content": system_prompt_updated}] + history + [{"role": "user", "content": message}]
    new_answer = openai_client.chat.completions.create(model="o4-mini", messages=messages)
    return new_answer.choices[0].message.content

# def chatting(message, history):
#     #system = system_prompt
#     # Si es la primera vez (no hay historia), ignoramos `message` y pedimos solo el saludo
#     if not history:
#         messages = [{"role": "system", "content": system_prompt}]
#         answer = openai_client.chat.completions.create(
#             model="o4-mini",
#             messages=messages
#         )
#         chat_response = answer.choices[0].message.content
#         return chat_response
#
#     messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": message}]
#     answer = openai_client.chat.completions.create(model="o4-mini", messages=messages)
#     chat_response = answer.choices[0].message.content
#
#     evaluation = evaluate(chat_response, message, history)
#
#     if evaluation.is_acceptable:
#         print("Pasó la evaluación - devolviendo respuesta")
#     else:
#         print("Falló la evaluación - reintentando")
#         print(evaluation.retroalimentation)
#         chat_response = rexecute(chat_response, message, history, evaluation.retroalimentation)
#     return chat_response

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
            "Has alcanzado el límite de uso para esta sesión. "
            "Si deseas continuar, contáctame directamente."
        )

    # 2️⃣ Registrar input del usuario
    register_token_usage(ip, [message])

    try:
        if not history:
            return safe_openai_chat(
                model="o4-mini",
                messages=[{"role": "system", "content": system_prompt}],
                context={"phase": "intro"}
            )

        messages = [{"role": "system", "content": system_prompt}] + history + [
            {"role": "user", "content": message}
        ]

        chat_response = safe_openai_chat(
            model="o4-mini",
            messages=messages,
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
).queue().launch()

gr.ChatInterface(chatting).launch()
