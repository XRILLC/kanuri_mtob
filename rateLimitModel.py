import os
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError
from google.api_core.exceptions import ResourceExhausted, InternalServerError
from openai import OpenAI
from openai import RateLimitError as OAIRateLimitError
from threading import Lock
from time import time, sleep

"""
This class assumes that it is initialized in the main thread
and then passed into a bunch of threads which call __call__.
As a result, the lock is shared, and the history is shared.  Rate 
limits on both Gemini and GPT are based on limiting how much happens
within a 1 minute interval.  To manage this efficiently, this
class keeps track of all requests which have been made within the last
minute.  When a limit is hit, calls sleep until the oldest call ages out
of the minute, and then the call is retried.
"""
class RateLimitModel:
    def __init__(self, model_id):
        self.model_id = model_id
        if "gemini" in model_id.lower():
            self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        elif "gpt" in model_id.lower():
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            raise Exception(f"I don't recognize that model type: {model_id}")
        self.history = []
        self.lock = Lock()

    def dropHistory(self):
        with self.lock:
            cur = time()
            if self.history != []:
                for i in range(len(self.history)):
                    if cur - self.history[i] < 60:
                        self.history = self.history[i:]
                        break
                else:
                    self.history = []
            if self.history != []:
                dur = 60 - (cur - self.history[0])
            else:
                dur = 1
        return dur
        
        
    def __call__(self, prompt, generation_config = None):
        while True:
            dur = self.dropHistory()
            try:
                if "gpt" in self.model_id:
                    response = self.client.responses.create(model=self.model_id, input=prompt, temperature=generation_config["temperature"], max_output_tokens=1000)
                    text = response.output[0].content[0].text
                else:
                    config = types.GenerateContentConfig(
                        safety_settings=[
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
                        ],
                        temperature=generation_config["temperature"],
                        max_output_tokens = 1000
                    )
                    response = self.client.models.generate_content(model=self.model_id, contents=prompt, config=config)
                    text = response.text
                break
            except (ResourceExhausted, OAIRateLimitError, ClientError):
                print("Hitting rate limit; sleeping for %ss" % (dur,))
                sleep(dur)
            except (InternalServerError, ServerError) as e:
                print(e)
                print("Hit a server error.  Waiting for 1 minute for it to clear up.")
                sleep(60)
            except Exception as e:
                print("UNKNOWN EXCEPTION!!! (%s)" % (type(e),))
                print(e)
        self.history.append(time())
        return text
