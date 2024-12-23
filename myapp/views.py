from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import base64
import os
import re
import json
import time
from django.conf import settings
from django.core.files.storage import default_storage
from together import Together
from PIL import Image

# Initialize Together API client with API key
client = Together(api_key="8202b96020b09cda9c60f0e8c0898008e68b84e4c3860b4adf36a246e28806aa")

# Function to encode an image to base64
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


# Function to preprocess the image (resize, enhance, etc.)
def preprocess_image(image_path):
    try:
        img = Image.open(image_path)
        img = img.convert("RGB")  # Ensure it's in RGB
        img = img.resize((1024, 1024))  # Resize image for better model handling
        processed_path = image_path.replace(".jpeg", "_processed.jpeg")
        img.save(processed_path)
        return processed_path
    except Exception as e:
        print(f"Error preprocessing image {image_path}: {e}")
        return image_path


# JSON-compatible prompt
basePrompt = basePrompt = """
You are an AI made to analyze object *length, width, depth, and any other possible measurements according to the object. Your output must be in **valid JSON format* and follow one of the three options below:

---

### *Option 1:*  
{
  "option": 1,
  "object": "[Object Name]",
  "readings": {
    "length": "[Measurement Data]",
    "width": "[Measurement Data]",
    "depth": "[Measurement Data]"
  },
  "accuracy": "[High/Moderate/Low]"
}

---

### *Option 2:*  
{
  "option": 2,
  "prediction": {
    "object": "[Object Name]",
    "readings": {
      "length": "[Measurement Data]",
      "width": "[Measurement Data]",
      "depth": "[Measurement Data]"
    }
  },
  "accuracy": "Low",
  "alert": "The image appears to be taken from less than the recommended distance (6–8 feet). This may affect measurement accuracy.",
  "recommendations": {
    "side_angle": "Front-facing or slightly angled (15–30° max)",
    "distance": "6–10 feet"
  }
}

---

### *Option 3:*  
{
  "option": 3,
  "prediction": {
    "object": "[Object Name]",
    "readings": {
      "length": "[Approx. Value]",
      "width": "[Approx. Value]",
      "depth": "[Approx. Value]"
    }
  },
  "accuracy": "Very Low",
  "error": "The image does not meet the minimum requirements for reliable measurement analysis due to poor image quality.",
  "recommendations": {
    "side_angle": "Front-facing or slightly angled (15–30° max)",
    "distance": "6–10 feet"
  }
}

---

*Make sure your output is a valid JSON object with no additional text or explanation outside the JSON structure.*
"""

# JSON Extraction Regex
json_pattern = r"\{.*?\}"

class ImageProcessingView(APIView):
    def post(self, request):
        image_folder = "./images/"
        image_files = request.FILES.getlist('images')
        cumulative_context = ""
        final_responses = {}

        # Make sure the images folder exists
        os.makedirs(image_folder, exist_ok=True)

        for idx, image_file in enumerate(image_files):
            # Save the image to disk
            image_path = os.path.join(image_folder, f"{idx + 1}.jpeg")
            with open(image_path, 'wb') as f:
                for chunk in image_file.chunks():
                    f.write(chunk)

            print(f"Processing {image_file.name}...")

            # Preprocess the image (optional, resizing for better model performance)
            processed_image_path = preprocess_image(image_path)
            base64_image = encode_image(processed_image_path)

            # Build messages with cumulative context
            messages = [
                {"role": "user", "content": [{"type": "text", "text": basePrompt + cumulative_context}]},
                {"role": "user",
                 "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
            ]

            try:
                response = client.chat.completions.create(
                    model="meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
                    messages=messages
                )

                # Log the raw response for debugging
                response_text = response.choices[0].message.content
                print(f"Response Text for {image_file.name}: {response_text}")

                json_match = re.search(json_pattern, response_text, re.DOTALL)

                if json_match:
                    json_data = json_match.group(0)
                    print(f"Extracted JSON: {json_data}\n")
                    final_responses[f"Image {idx + 1}"] = json_data
                    cumulative_context += f"\nPrevious Image {idx + 1} Response:\n{json_data}"

                else:
                    print(f"No valid JSON response received for {image_file.name}")
                    final_responses[f"Image {idx + 1}"] = "No valid JSON response received."

            except Exception as e:
                print(f"Error processing {image_file.name}: {e}")
                final_responses[f"Image {idx + 1}"] = f"Error - {str(e)}"
                time.sleep(2)  # Prevent rapid retries

        # Send extracted responses to Together API to ask for range
        final_range_result = self.send_to_together_for_range(final_responses)

        # Clean the response to remove newline and backslash characters
        cleaned_final_range_result = self.clean_response(final_range_result)

        # Clean individual image responses
        cleaned_responses = {key: self.clean_response(value) for key, value in final_responses.items()}

        # Format final response with cleaned data
        final_response = {
            **cleaned_responses,
            "final_range_result": cleaned_final_range_result
        }

        return Response({"results": final_response}, status=status.HTTP_200_OK)

    def send_to_together_for_range(self, final_responses):
        # Prepare the response to be sent to the Together API
        range_request_data = {"responses": final_responses}

        # Create the new message prompt to ask for range of measurements
        range_prompt = """
                        You are an AI designed to process JSON outputs containing object measurements from multiple images. Your task is to analyze these inputs, calculate refined measurement ranges, and provide a final JSON output with minimum, maximum, and average values for each dimension. YOUR OUTPUT IS LIMITED TO JSON DO NOT OUTPUT ANYTHING OTHER THEN JSON if you understand then start your output with the required json as explained
                        
                        ### *Input Example:*  
                        json
                        "results": {
                            "Image 1": "{  \"option\": 2,  \"prediction\": {    \"object\": \"Laptop\",    \"readings\": {      \"length\": \"16-18 inches\",      \"width\": \"11.6-13 inches\",      \"depth\": \"8-11 inches\"    }",
                            "Image 2": "No valid JSON response received.",
                            "Image 3": "{  \"option\": 1,  \"object\": \"Laptop\",  \"readings\": {    \"length\": \"16-18 inches\",    \"width\": \"11.6-13 inches\",    \"depth\": \"8-11 inches\"  }"
                        }
                        
                        
                        ### *Your Task:*  
                        1. *Extract valid JSON entries:* Ignore any invalid or missing JSON responses.  
                        2. *Object Consistency:* Ensure that the object name is consistent across valid entries.  
                        3. *Calculate Ranges:* For each dimension (length, width, depth), determine:  
                           - *Min:* The lowest value across all readings.  
                           - *Max:* The highest value across all readings.  
                           - *Average:* Calculate the average value from valid readings.  
                        4. *Generate Final JSON Output:* Present the refined measurements in a standardized JSON format.
                        
                        ### *Expected Output Format:*  
                        json
                        {
                          "object": "[Object Name]",
                          "readings": {
                            "length": {
                              "min": [minimum value],
                              "max": [maximum value],
                              "average": [average value]
                            },
                            "width": {
                              "min": [minimum value],
                              "max": [maximum value],
                              "average": [average value]
                            },
                            "depth": {
                              "min": [minimum value],
                              "max": [maximum value],
                              "average": [average value]
                            }
                          },
                          "accuracy": "Refined from multiple inputs"
                        }
                        
                        
                        ### *Constraints:*  
                        - Always ensure valid JSON syntax in your output.  
                        - Discard invalid or incomplete entries but mention their exclusion in the process.  
                        - Only include dimensions that have valid measurements across entries.  
                        
                        Your output *must* strictly adhere to the specified JSON format.
                        
                        YOUR OUTPUT IS LIMITED TO JSON DO NOT OUTPUT ANYTHING OTHER THEN JSON if you understand then start your output with the required json as explained
                        """
        # Send the data to Together API with the range request
        try:
            messages = [
                {"role": "user", "content": [{"type": "text", "text": range_prompt}]},
                {"role": "user", "content": [{"type": "text", "text": json.dumps(range_request_data)}]}
            ]

            response = client.chat.completions.create(
                model="meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
                messages=messages
            )

            # Log the raw response for debugging
            range_response_text = response.choices[0].message.content
            print(f"Range Response: {range_response_text}")

            return range_response_text

        except Exception as e:
            print(f"Error sending range request: {e}")
            return {"error": "An error occurred while calculating the range."}

    def clean_response(self, response_text):
        """
        Cleans up the response text by removing newline characters and backslashes.
        """
        cleaned_response = response_text.replace("\n", "").replace("\\", "")
        return cleaned_response
