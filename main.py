from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader
import pdfplumber
from pydantic import BaseModel
import os
import gradio as gr
import re

load_dotenv(override=True)
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
system_prompt = f"Estás actuando como {name}. Estás respondiendo a preguntas en el sitio web de {name}, " + \
    "particularment preguntas relacionadas con la carrera, antecedentes, habilidades y experiencia de {name}. " + \
    "Tu responsabilidad es representar a {name} para las interacciones en el sitio web de la manera más fiel posible. " + \
    "Se te proporciona un resumen de los antecedentes de {name} y el perfil que puedes usar para responder preguntas. " + \
    "Sé profesional y atractivo, como si hablaras con un cliente potencial o futuro empleador que se encontró con el sitio web. " + \
    "Si te preguntan en inglés, contesta en inglés. Si lo hacen en español, contesta en español. " + \
    "Si no sabes la respuesta, dilo."

system_prompt += f"\n\n## Resumen:\n{resume}\n\n## Perfil de LinedIn:\n{profile}\n\n"
system_prompt += f"Con este contexto, por favor chatea con el usuario, manteniéndote siempre en el personaje de {name}."

#print(system_prompt)

def chat(message, history):
    messages = [{"role": "system", "content": prompt}]

    for item in history:
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
            if role and content:
                messages.append({"role": role, "content": content})
        elif isinstance(item, (list, tuple)):
            if len(item) >= 1 and item[0]:
                messages.append({"role": "user", "content": item[0]})
            if len(item) >= 2 and item[1]:
                messages.append({"role": "assistant", "content": item[1]})

    messages.append({"role": "user", "content": message})

    response = openai_client.chat.completions.create(
        model="o4-mini",
        messages=messages
    )

    return response.choices[0].message.content

# gr.ChatInterface(chat).launch()

class Evaluation(BaseModel):
    is_acceptable: bool
    retroalimentation: str

prompt_evaluation_system = f"Eres un evaluador que decide si una respuesta a una pregunta es acedptable. " + \
    "Se te proporciona una conversación entre un usuario y un agente. Tu tarea es decidir si la última " + \
    "respuesta del agente es de calidad aceptable." + \
    "El agente está interpretando del papel de {name} y está representando a {name} en su sitio web. " + \
    "Se ha instruido al agente para que sea profesional y atractivo, como si hablara con un cliente potencial " + \
    "o futuro empleador que se encontró con el sitio web. " + \
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
    answer_eval = gemini.beta.chat.completions.parse(model="gemini-flash-latest", messages=messages, response_format=Evaluation)
    return answer_eval.choices[0].message.parsed

question = "¿Qué idiomas manejas?"
messages = [{"role": "system", "content": system_prompt}] + [{"role": "user", "content": question}]
answer = openai_client.chat.completions.create(model="o4-mini", messages=messages)
chat_response = answer.choices[0].message.content

print(chat_response)

# print(evaluate(chat_response, question, messages[:1]))

def rexecute(answer, message, history, retroalimentation):
    system_prompt_updated = system_prompt + "\n\n## Respuesta anterior rechazada." + \
        "\nAcabas de intentar responder, pero el control de calidad rechazó tu respuesta.\n"
    system_prompt_updated += f"## Tu redspuesta intentada:\n{answer}\n\n"
    system_prompt_updated += f"## Razón del rechazo:\n{retroalimentation}\n\n"
    messages = [{"role": "system", "content": system_prompt_updated}] + history + [{"role": "user", "content": message}]
    new_answer = openai_client.chat.completions.create(model="o4-mini", messages=messages)
    return new_answer.choices[0].message.content

def chatting(message, history):
    system = system_prompt
    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": message}]
    answer = openai_client.chat.completions.create(model="o4-mini", messages=messages)
    chat_response = answer.choices[0].message.content

    evaluation = evaluate(chat_response, message, history)

    if evaluation.is_acceptable:
        print("Pasó la evaluación - devolviendo respuesta")
    else:
        print("Falló la evaluación - reintentando")
        print(evaluation.retroalimentation)
        chat_response = rexecute(chat_response, message, history, evaluation.retroalimentation)
    return chat_response

gr.ChatInterface(chatting).launch()
