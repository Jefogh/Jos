import base64
import io
import random
import requests
import time
from PIL import Image
from flet import (
    Page, Text, ElevatedButton, TextField, Image as FletImage, Row, Column,
    Scrollable, Container, colors, alignment
)

class CaptchaApp:
    def __init__(self, page: Page):
        self.page = page
        self.page.title = "Captcha Solver"
        self.page.window_width = 800
        self.page.window_height = 600

        self.accounts = {}
        self.active_captchas = {}
        self.failed_accounts = set()
        self.captcha_queue = []
        self.current_captcha_container = None

        self.notification_text = Text("", visible=False, color=colors.YELLOW)
        self.page.add(self.notification_text)

        self.add_account_button = ElevatedButton(
            text="Add Account", on_click=self.add_account
        )
        self.page.add(self.add_account_button)

        self.request_all_cap1_button = ElevatedButton(
            text="Request All Cap 1s", on_click=self.request_all_cap1s
        )
        self.page.add(self.request_all_cap1_button)

        self.accounts_column = Column(scroll="auto", expand=True)
        self.page.add(self.accounts_column)

    def show_notification(self, message):
        self.notification_text.value = f"Notification: {message}"
        self.notification_text.visible = True
        self.page.update()
        time.sleep(5)
        self.notification_text.visible = False
        self.page.update()

    def add_account(self, e):
        username = self.page.dialog.show_input_dialog("Enter Username:", "", "")
        if not username:
            return
        password = self.page.dialog.show_input_dialog("Enter Password:", "", "", password=True)
        if not password:
            return

        user_agent = self.generate_user_agent()
        session = self.create_session(user_agent)
        login_success = self.login(username, password, user_agent, session)
        if login_success:
            self.accounts[username] = {
                'password': password,
                'user_agent': user_agent,
                'session': session,
                'captcha_id1': None,
                'captcha_id2': None
            }
            self.create_account_ui(username)
        else:
            self.show_notification(f"Failed to login for user {username}")

    def create_account_ui(self, username):
        account_row = Row()
        account_label = Text(f"Account: {username}")
        account_row.controls.append(account_label)

        captcha_id1 = self.page.dialog.show_input_dialog("Enter Captcha ID 1:", "", "")
        captcha_id2 = self.page.dialog.show_input_dialog("Enter Captcha ID 2:", "", "")
        self.accounts[username]['captcha_id1'] = captcha_id1
        self.accounts[username]['captcha_id2'] = captcha_id2

        cap1_button = ElevatedButton(
            text="Cap 1", on_click=lambda e: self.request_captcha(username, captcha_id1)
        )
        cap2_button = ElevatedButton(
            text="Cap 2", on_click=lambda e: self.request_captcha(username, captcha_id2)
        )
        remove_button = ElevatedButton(
            text="×", on_click=lambda e: self.remove_account_ui(account_row, username)
        )

        account_row.controls.extend([cap1_button, cap2_button, remove_button])
        self.accounts_column.controls.append(account_row)
        self.page.update()

    def remove_account_ui(self, account_row, username):
        self.accounts_column.controls.remove(account_row)
        del self.accounts[username]
        self.failed_accounts.discard(username)
        self.active_captchas = {k: v for k, v in self.active_captchas.items() if v != username}
        self.page.update()

    def request_all_cap1s(self, e):
        for username, account_data in self.accounts.items():
            captcha_id1 = account_data['captcha_id1']
            self.request_captcha(username, captcha_id1)

    def create_session(self, user_agent):
        session = requests.Session()
        session.headers.update(self.generate_headers(user_agent))
        return session

    def login(self, username, password, user_agent, session, retry_count=3):
        login_url = 'https://api.ecsc.gov.sy:8080/secure/auth/login'
        login_data = {
            'username': username,
            'password': password
        }

        for attempt in range(retry_count):
            try:
                response = session.post(login_url, json=login_data)
                if response.status_code == 200:
                    return True
                elif response.status_code in {401, 402, 403}:
                    self.show_notification(f"Error {response.status_code}. Retrying...")
                    if response.status_code == 401:
                        self.failed_accounts.add(username)
                        return False
                else:
                    return False
            except requests.RequestException as e:
                self.show_notification(f"Request error: {e}. Retrying...")
                time.sleep(2)
            except Exception as e:
                self.show_notification(f"Unexpected error: {e}. Retrying...")
                time.sleep(2)

        return False

    def request_captcha(self, username, captcha_id):
        if username in self.failed_accounts:
            self.show_notification(f"Account {username} has failed. Please check the credentials.")
            return

        session = self.accounts[username].get('session')
        if not session:
            self.show_notification(f"No session found for user {username}")
            return

        captcha_data = self.get_captcha(session, captcha_id)
        if captcha_data:
            self.captcha_queue.append((username, captcha_id, captcha_data))
            if not self.current_captcha_container:
                self.process_next_captcha()
        else:
            self.show_notification(f"Failed to get captcha for {username} with ID {captcha_id}")

    def get_captcha(self, session, captcha_id):
        try:
            captcha_url = f"https://api.ecsc.gov.sy:8080/files/fs/captcha/{captcha_id}"
            response = session.get(captcha_url)
            if response.status_code == 200:
                response_data = response.json()
                if 'file' in response_data:
                    return response_data['file']
            return None
        except requests.RequestException as e:
            self.show_notification(f"Request error: {e}")
            return None

    def process_next_captcha(self):
        if self.captcha_queue:
            username, captcha_id, captcha_data = self.captcha_queue.pop(0)
            self.show_captcha(captcha_data, username, captcha_id)

    def show_captcha(self, captcha_data, username, captcha_id):
        try:
            captcha_base64 = captcha_data.split(",")[1] if ',' in captcha_data else captcha_data
            captcha_image_data = base64.b64decode(captcha_base64)
            captcha_image = Image.open(io.BytesIO(captcha_image_data))
            captcha_image = captcha_image.resize((300, 150))

            if self.current_captcha_container:
                self.page.remove(self.current_captcha_container)

            captcha_image_flet = FletImage(src=captcha_image_data)
            captcha_input = TextField(width=400)

            submit_button = ElevatedButton(
                text="Submit",
                on_click=lambda e: self.submit_captcha(username, captcha_id, captcha_input.value)
            )

            self.current_captcha_container = Container(
                content=Column([
                    captcha_image_flet,
                    captcha_input,
                    submit_button
                ]),
                alignment=alignment.center
            )
            self.page.add(self.current_captcha_container)
            self.page.update()

        except Exception as e:
            self.show_notification(f"Error displaying captcha. Error: {e}")

    def submit_captcha(self, username, captcha_id, captcha_solution):
        session = self.accounts[username].get('session')
        get_url = f"https://api.ecsc.gov.sy:8080/rs/reserve?id={captcha_id}&captcha={captcha_solution}"
        get_response = session.get(get_url)

        if get_response.status_code == 200:
            self.show_notification("Captcha solved successfully!")
        else:
            self.show_notification(f"Failed to solve captcha. Status code: {get_response.status_code}")

        if self.current_captcha_container:
            self.page.remove(self.current_captcha_container)
            self.current_captcha_container = None
        self.process_next_captcha()

    def generate_headers(self, user_agent):
        headers = {
            'User-Agent': user_agent,
            'Content-Type': 'application/json',
            'Source': 'WEB',
            'Accept': 'application/json, text/plain, */*',
            'Referer': 'https://ecsc.gov.sy/',
            'Origin': 'https://ecsc.gov.sy',
            'Connection': 'keep-alive'
        }
        return headers

    def generate_user_agent(self):
        user_agent_list = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.1 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36",
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.106 Safari/537.36",
            "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36"
        ]
        return random.choice(user_agent_list)

def main(page: Page):
    app = CaptchaApp(page)

if __name__ == "__main__":
    import flet as ft
    ft.app(target=main)
