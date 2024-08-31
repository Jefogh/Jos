import base64
import random
import time
import threading
import cv2
import numpy as np
from PIL import Image
import httpx
import easyocr
import re
import json
import os
import flet as ft

# تحسين إعدادات EasyOCR لتسريع العملية
reader = easyocr.Reader(['en'], gpu=False, model_storage_directory=os.path.join(os.getcwd(), "model"), download_enabled=True)


class CaptchaApp:
    def __init__(self, page):
        self.page = page
        self.accounts = {}
        self.background_images = []
        self.last_status_code = None
        self.last_response_text = None
        self.corrections = self.load_corrections()

        self.page.title = "Captcha Solver"
        self.page.window_width = 1000
        self.page.window_height = 600
        self.page.scroll = ft.ScrollMode.AUTO

        self.main_frame = ft.Column(scroll=ft.ScrollMode.AUTO)
        self.page.add(self.main_frame)

        self.create_widgets()

    def create_widgets(self):
        """Create UI widgets for user interactions."""
        self.add_account_button = ft.ElevatedButton("Add Account", on_click=self.add_account)
        self.upload_background_button = ft.ElevatedButton("Upload Backgrounds", on_click=self.upload_backgrounds)

        self.main_frame.controls.append(self.add_account_button)
        self.main_frame.controls.append(self.upload_background_button)
        self.page.update()

    def upload_backgrounds(self, e):
        """Upload background images for processing."""
        file_dialog = ft.FilePicker(
            on_result=lambda result: self.handle_background_upload(result),
            allow_multiple=True,
            file_type=ft.FileType.IMAGE
        )
        self.page.overlay.append(file_dialog)
        file_dialog.pick_files()

    def handle_background_upload(self, result):
        """Handle the background upload result."""
        background_paths = result.files
        if background_paths:
            self.background_images = [cv2.imread(path.path) for path in background_paths]
            self.page.snack_bar = ft.SnackBar(ft.Text(f"{len(self.background_images)} background images uploaded successfully!"))
            self.page.snack_bar.open = True
            self.page.update()

    def add_account(self, e):
        """Add a new account for captcha solving."""
        def save_account(dialog, username, password):
            user_agent = self.generate_user_agent()
            session = self.create_session(user_agent)
            if self.login(username, password, session):
                self.accounts[username] = {
                    'password': password,
                    'user_agent': user_agent,
                    'session': session,
                    'captcha_id1': None,
                    'captcha_id2': None
                }
                self.create_account_ui(username)
            else:
                self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to login for user {username}"))
                self.page.snack_bar.open = True
            dialog.open = False
            self.page.update()

        username_input = ft.TextField(label="Enter Username:")
        password_input = ft.TextField(label="Enter Password:", password=True)

        dialog = ft.AlertDialog(
            title=ft.Text("Add Account"),
            content=ft.Column([username_input, password_input]),
            actions=[
                ft.TextButton("Save", on_click=lambda _: save_account(dialog, username_input.value, password_input.value)),
                ft.TextButton("Cancel", on_click=lambda _: setattr(dialog, 'open', False)),
            ]
        )

        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    def create_account_ui(self, username):
        """Create the UI elements for a specific account."""
        captcha_id1_input = ft.TextField(label="Enter Captcha ID 1:")
        captcha_id2_input = ft.TextField(label="Enter Captcha ID 2:")

        def request_captcha(captcha_id):
            threading.Thread(target=self.request_captcha, args=(username, captcha_id)).start()

        account_controls = [
            ft.Text(f"Account: {username}"),
            captcha_id1_input,
            captcha_id2_input,
            ft.ElevatedButton("Cap 1", on_click=lambda _: request_captcha(captcha_id1_input.value)),
            ft.ElevatedButton("Cap 2", on_click=lambda _: request_captcha(captcha_id2_input.value)),
            ft.ElevatedButton("Request All", on_click=lambda _: self.request_all_captchas(username))
        ]

        account_frame = ft.Column(account_controls)
        self.main_frame.controls.append(account_frame)
        self.page.update()

    def request_all_captchas(self, username):
        """Request all captchas for the specified account."""
        self.request_captcha(username, self.accounts[username]['captcha_id1'])
        self.request_captcha(username, self.accounts[username]['captcha_id2'])

    @staticmethod
    def create_session(user_agent):
        """Create an HTTP session with custom headers."""
        return httpx.Client(headers=CaptchaApp.generate_headers(user_agent))

    def login(self, username, password, session, retry_count=3):
        """Attempt to log in to the account."""
        login_url = 'https://api.ecsc.gov.sy:8080/secure/auth/login'
        login_data = {'username': username, 'password': password}

        for attempt in range(retry_count):
            try:
                response = session.post(login_url, json=login_data)

                if response.status_code == 200:
                    return True
                elif response.status_code in {401, 402, 403}:
                    continue
                else:
                    return False
            except httpx.RequestError as e:
                continue
        return False

    def request_captcha(self, username, captcha_id):
        """Request a captcha image for processing."""
        session = self.accounts[username].get('session')
        if not session:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"No session found for user {username}"))
            self.page.snack_bar.open = True
            self.page.update()
            return

        try:
            options_url = f"https://api.ecsc.gov.sy:8080/rs/reserve?id={captcha_id}&captcha=0"
            session.options(options_url)
        except httpx.RequestError as e:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to send OPTIONS request: {e}"))
            self.page.snack_bar.open = True
            self.page.update()
            return

        captcha_data = self.get_captcha(session, captcha_id)
        if captcha_data:
            self.show_captcha(captcha_data, username, captcha_id)
        else:
            if self.last_status_code == 403:
                if self.login(username, self.accounts[username]['password'], session):
                    self.page.snack_bar = ft.SnackBar(ft.Text(f"Re-login successful for user {username}. Please request the captcha again."))
                    self.page.snack_bar.open = True
                else:
                    self.page.snack_bar = ft.SnackBar(ft.Text(f"Re-login failed for user {username}. Please check credentials."))
                    self.page.snack_bar.open = True
                self.page.update()
            else:
                self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to get captcha. Status code: {self.last_status_code}, Response: {self.last_response_text}"))
                self.page.snack_bar.open = True
                self.page.update()

    def get_captcha(self, session, captcha_id):
        """Retrieve the captcha image data."""
        try:
            captcha_url = f"https://api.ecsc.gov.sy:8080/files/fs/captcha/{captcha_id}"
            response = session.get(captcha_url)

            self.last_status_code = response.status_code
            self.last_response_text = response.text

            if response.status_code == 200:
                response_data = response.json()
                return response_data.get('file')
        except Exception as e:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to get captcha: {e}"))
            self.page.snack_bar.open = True
            self.page.update()
        return None

    def show_captcha(self, captcha_data, username, captcha_id):
        """Display the captcha image for user input."""
        try:
            captcha_base64 = captcha_data.split(",")[1] if ',' in captcha_data else captcha_data
            captcha_image_data = base64.b64decode(captcha_base64)

            with open("captcha.jpg", "wb") as f:
                f.write(captcha_image_data)

            captcha_image = cv2.imread("captcha.jpg")
            processed_image = self.process_captcha(captcha_image)

            processed_image = cv2.resize(processed_image, (110, 60))
            processed_image[np.all(processed_image == [0, 0, 0], axis=-1)] = [255, 255, 255]

            img_pil = Image.fromarray(cv2.cvtColor(processed_image, cv2.COLOR_BGR2RGB))
            img_pil.thumbnail((400, 400))
            img_byte_arr = io.BytesIO()
            img_pil.save(img_byte_arr, format='PNG')
            img_data = img_byte_arr.getvalue()

            captcha_image = ft.Image(src_base64=base64.b64encode(img_data).decode('utf-8'))

            ocr_output_entry = ft.TextField(width=400)
            captcha_entry = ft.TextField()

            def submit_captcha():
                threading.Thread(target=self.submit_captcha, args=(username, captcha_id, captcha_entry.value)).start()

            submit_button = ft.ElevatedButton("Submit Captcha", on_click=submit_captcha)

            img_array = np.array(processed_image)
            predictions = reader.readtext(img_array, detail=0, allowlist='0123456789+-*/')
            corrected_text, _ = self.correct_and_highlight(predictions, img_array)
            captcha_solution = self.solve_captcha(corrected_text)

            ocr_output_entry.value = corrected_text
            captcha_entry.value = captcha_solution

            captcha_frame = ft.Column([captcha_image, ocr_output_entry, captcha_entry, submit_button])
            self.main_frame.controls.append(captcha_frame)
            self.page.update()

        except Exception as e:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to show captcha: {e}"))
            self.page.snack_bar.open = True
            self.page.update()

    def process_captcha(self, captcha_image):
        """Apply advanced image processing to remove the background using added backgrounds while keeping original colors."""
        captcha_image = cv2.resize(captcha_image, (110, 60))

        if not self.background_images:
            return captcha_image

        best_background = None
        min_diff = float('inf')

        for background in self.background_images:
            background = cv2.resize(background, (110, 60))
            processed_image = self.remove_background_keep_original_colors(captcha_image, background)
            gray_diff = cv2.cvtColor(processed_image, cv2.COLOR_BGR2GRAY)
            score = np.sum(gray_diff)

            if score < min_diff:
                min_diff = score
                best_background = background

        if best_background is not None:
            cleaned_image = self.remove_background_keep_original_colors(captcha_image, best_background)
            return cleaned_image
        else:
            return captcha_image

    @staticmethod
    def remove_background_keep_original_colors(captcha_image, background_image):
        """Remove background from captcha image while keeping the original colors of elements."""
        if background_image.shape != captcha_image.shape:
            background_image = cv2.resize(background_image, (captcha_image.shape[1], captcha_image.shape[0]))

        diff = cv2.absdiff(captcha_image, background_image)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
        result = cv2.bitwise_and(captcha_image, captcha_image, mask=mask)

        return result

    def submit_captcha(self, username, captcha_id, captcha_solution):
        """Submit the captcha solution to the server."""
        session = self.accounts[username].get('session')
        if not session:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"No session found for user {username}"))
            self.page.snack_bar.open = True
            self.page.update()
            return

        try:
            options_url = f"https://api.ecsc.gov.sy:8080/rs/reserve?id={captcha_id}&captcha={captcha_solution}"
            session.options(options_url)
        except httpx.RequestError as e:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to send OPTIONS request: {e}"))
            self.page.snack_bar.open = True
            self.page.update()
            return

        try:
            get_url = f"https://api.ecsc.gov.sy:8080/rs/reserve?id={captcha_id}&captcha={captcha_solution}"
            response = session.get(get_url)

            if response.status_code == 200:
                response_data = response.json()
                message = response_data.get('message', "Captcha submitted successfully!")
                self.page.snack_bar = ft.SnackBar(ft.Text(message))
                self.page.snack_bar.open = True
            else:
                self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to submit captcha. Status code: {response.status_code}, Response: {response.text}"))
                self.page.snack_bar.open = True

        except Exception as e:
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Failed to submit captcha: {e}"))
            self.page.snack_bar.open = True
        self.page.update()

    @staticmethod
    def generate_headers(user_agent):
        """Generate HTTP headers for the session."""
        return {
            'User-Agent': user_agent,
            'Content-Type': 'application/json',
            'Source': 'WEB',
            'Accept': 'application/json, text/plain, */*',
            'Referer': 'https://ecsc.gov.sy/',
            'Origin': 'https://ecsc.gov.sy',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }

    @staticmethod
    def generate_user_agent():
        """Generate a random user agent string."""
        user_agent_list = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv=89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/13.1.1 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/56.0.2924.87 Safari/537.36",
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/47.0.2526.106 Safari/537.36",
            "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36"
        ]

        return random.choice(user_agent_list)

    def correct_and_highlight(self, predictions, image):
        """Correct OCR predictions and apply color highlights to numbers and operators."""
        corrections = {
            'O': '0', 'S': '5', 'I': '1', 'B': '8', 'G': '6',
            'Z': '2', 'T': '7', 'A': '4', 'X': '*', '×': '*', 'L': '1',
            'H': '8', '_': '-', '/': '7', '£': '8', '&': '8'
        }

        num_color = (0, 255, 0)  # Green for numbers
        op_color = (0, 0, 255)  # Red for operators
        corrected_text = ""

        for text in predictions:
            text = text.strip().upper()
            for char in text:
                corrected_char = corrections.get(char, char)
                if corrected_char.isdigit():
                    corrected_text += corrected_char
                elif corrected_char in "+-*xX×":
                    corrected_text += corrected_char
                else:
                    corrected_text += corrected_char

        return corrected_text, image

    def learn_from_correction(self, original_text, corrected_text):
        """Learn from user correction and store the correction in a file."""
        if original_text != corrected_text:
            self.corrections[original_text] = corrected_text
            self.save_corrections()

    def save_corrections(self):
        """Save corrections to a file on the desktop."""
        file_path = os.path.join(r"C:\Users\Gg\Desktop", "corrections.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.corrections, f, ensure_ascii=False, indent=4)

    def load_corrections(self):
        """Load corrections from a file on the desktop."""
        file_path = os.path.join(r"C:\Users\Gg\Desktop", "corrections.json")
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    @staticmethod
    def solve_captcha(corrected_text):
        """Solve the captcha by extracting two numbers and one operator."""
        corrected_text = re.sub(r"[._/]", "", corrected_text)

        numbers = re.findall(r'\d+', corrected_text)
        operators = re.findall(r'[+*xX-]', corrected_text)

        if len(numbers) == 2 and len(operators) == 1:
            num1, num2 = map(int, numbers)
            operator = operators[0]

            if operator in ['*', '×', 'x']:
                return abs(num1 * num2)
            elif operator == '+':
                return abs(num1 + num2)
            elif operator == '-':
                return abs(num1 - num2)

        if len(corrected_text) == 3 and corrected_text[0] in {'+', '-', '*', 'x', '×'}:
            num1, operator, num2 = corrected_text[1], corrected_text[0], corrected_text[2]
            num1, num2 = int(num1), int(num2)

            if operator in ['*', '×', 'x']:
                return abs(num1 * num2)
            elif operator == '+':
                return abs(num1 + num2)
            elif operator == '-':
                return abs(num1 - num2)

        return None


def main(page: ft.Page):
    app = CaptchaApp(page)


if __name__ == "__main__":
    ft.app(target=main)
