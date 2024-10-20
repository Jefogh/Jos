import base64
import random
import time
import threading
import tkinter as tk
from tkinter import simpledialog, Scrollbar, filedialog, ttk
import requests
import cv2
import numpy as np
from PIL import Image, ImageTk
import torch
import torch.nn as nn
import torchvision.transforms as transforms
from torchvision import models
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

cpu_device = torch.device("cpu")


class TrainedModel:
    def __init__(self):
        start_time = time.time()
        self.model = models.squeezenet1_0(weights=None)
        self.model.classifier[1] = nn.Conv2d(512, 30, kernel_size=(1, 1), stride=(1, 1))
        model_path = "C:/Users/ccl/Desktop/trained_model.pth"
        self.model.load_state_dict(torch.load(model_path, map_location=cpu_device, weights_only=True))
        self.model = self.model.to(cpu_device)
        self.model.eval()
        print(f"Model loaded in {time.time() - start_time:.4f} seconds")

    def predict(self, img):
        start_time = time.time()
        resized_image = cv2.resize(img, (160, 90))
        print(f"Image resizing (OpenCV) took {time.time() - start_time:.4f} seconds")

        pil_image = Image.fromarray(cv2.cvtColor(resized_image, cv2.COLOR_BGR2RGB))
        preprocess = transforms.Compose([
            transforms.Grayscale(num_output_channels=3),
            transforms.ToTensor(),
            transforms.Normalize([0.5], [0.5], [0.5]),
        ])
        tensor_image = preprocess(pil_image).unsqueeze(0).to(cpu_device)
        print(f"Image preprocessing took {time.time() - start_time:.4f} seconds")

        start_time = time.time()
        with torch.no_grad():
            outputs = self.model(tensor_image).view(-1, 30)
        print(f"Model prediction took {time.time() - start_time:.4f} seconds")

        num1_preds = outputs[:, :10]
        operation_preds = outputs[:, 10:13]
        num2_preds = outputs[:, 13:]

        _, num1_predicted = torch.max(num1_preds, 1)
        _, operation_predicted = torch.max(operation_preds, 1)
        _, num2_predicted = torch.max(num2_preds, 1)

        operation_map = {0: "+", 1: "-", 2: "×"}
        predicted_operation = operation_map[operation_predicted.item()]

        del tensor_image
        return num1_predicted.item(), predicted_operation, num2_predicted.item()


class ExpandingCircle:
    def __init__(self, canvas, x, y, max_radius, color):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.max_radius = max_radius
        self.radius = 10
        self.growing = True
        self.circle = self.canvas.create_oval(self.x - self.radius, self.y - self.radius,
                                              self.x + self.radius, self.y + self.radius,
                                              outline=color)
        self.expand_circle()

    def expand_circle(self):
        if self.growing:
            self.radius += 2
            if self.radius >= self.max_radius:
                self.growing = False
        else:
            self.radius -= 2
            if self.radius <= 10:
                self.growing = True

        self.canvas.coords(self.circle, self.x - self.radius, self.y - self.radius,
                           self.x + self.radius, self.y + self.radius)
        self.job = self.canvas.after(50, self.expand_circle)

    def stop(self):
        if hasattr(self, 'job'):
            self.canvas.after_cancel(self.job)
        self.canvas.delete(self.circle)


class CaptchaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Captcha Solver with Improved Deep Learning")
        self.root.geometry("1000x600")
        self.accounts = {}
        self.background_images = []
        self.last_status_code = None
        self.last_response_text = None
        self.captcha_frame = None
        self.trained_model = None
        self.canvas = None
        self.scrollbar = None
        self.main_frame = None
        self.add_account_button = None
        self.upload_background_button = None
        self.notification_label = None
        self.time_label = None
        self.executor = ThreadPoolExecutor(max_workers=4)

        self.load_model()
        self.setup_ui()

    def load_model(self):
        print("Loading model...")
        start_time = time.time()
        self.trained_model = TrainedModel()
        print(f"Model loaded and ready in {time.time() - start_time:.4f} seconds")

    def setup_ui(self):
        self.canvas = tk.Canvas(self.root)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar = Scrollbar(self.root, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.main_frame = tk.Frame(self.canvas)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_window((0, 0), window=self.main_frame, anchor=tk.NW)
        self.main_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.notification_label = tk.Label(self.root, text="", fg="white", bg="blue", font=("Helvetica", 12))
        self.notification_label.pack(fill=tk.X)
        self.time_label = tk.Label(self.root, text="", fg="white", bg="black", font=("Helvetica", 12))
        self.time_label.pack(side=tk.BOTTOM, fill=tk.X)

        self.create_widgets()
    def create_widgets(self):
        self.add_account_button = tk.Button(self.main_frame, text="Add Account", command=self.add_account)
        self.add_account_button.pack()

        self.upload_background_button = tk.Button(self.main_frame, text="Upload Backgrounds",
                                                  command=self.upload_backgrounds)
        self.upload_background_button.pack()

        self.login_button = tk.Button(self.main_frame, text="Login", command=self.login_saved_accounts)
        self.login_button.pack()

    def login_saved_accounts(self):
        for username, account_info in self.accounts.items():
            session = account_info.get("session")
            if not session or not self.is_session_valid(session):
                user_agent = self.generate_user_agent()
                session = self.create_session(user_agent)
                password = account_info.get("password")

                if self.login(username, password, session):
                    self.accounts[username]["session"] = session
                    self.update_notification(f"Login successful for {username}", "green")
                else:
                    self.update_notification(f"Login failed for {username}", "red")

    def is_session_valid(self, session):
        try:
            test_url = "https://api.ecsc.gov.sy:8080/some_endpoint_to_check_session"
            response = session.get(test_url)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def create_account_ui(self, username):
        account_frame = tk.Frame(self.main_frame)
        account_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(account_frame, text=f"Account: {username}").pack(side=tk.LEFT)

        captcha_id1 = simpledialog.askstring("Input", "Enter Captcha ID 1:")
        captcha_id2 = simpledialog.askstring("Input", "Enter Captcha ID 2:")

        self.accounts[username]["captcha_id1"] = captcha_id1
        self.accounts[username]["captcha_id2"] = captcha_id2

        loading_indicator1 = ttk.Progressbar(account_frame, mode='indeterminate')
        loading_indicator2 = ttk.Progressbar(account_frame, mode='indeterminate')

        cap1_button = tk.Button(account_frame, text="Cap 1",
                                command=lambda: threading.Thread(
                                    target=self.request_captcha,
                                    args=(username, captcha_id1, loading_indicator1)
                                ).start())
        cap1_button.pack(padx=8, pady=5)
        loading_indicator1.pack(padx=8, pady=5)

        cap2_button = tk.Button(account_frame, text="Cap 2",
                                command=lambda: threading.Thread(
                                    target=self.request_captcha,
                                    args=(username, captcha_id2, loading_indicator2)
                                ).start())
        cap2_button.pack(padx=8, pady=5)
        loading_indicator2.pack(padx=8, pady=5)

    def request_captcha(self, username, captcha_id, loading_indicator):
        loading_indicator.start()

        session = self.accounts[username].get("session")
        if not session:
            self.update_notification(f"No session found for user {username}", "red")
            loading_indicator.stop()
            return

        self.spinner_canvas = tk.Canvas(self.main_frame, width=100, height=100)
        self.spinner_canvas.pack(pady=10)
        self.spinner = ExpandingCircle(self.spinner_canvas, 50, 50, 30, 'blue')

    def request_captcha(self, username, captcha_id, loading_indicator):
        loading_indicator.start()

        session = self.accounts[username].get("session")
        if not session:
            self.update_notification(f"No session found for user {username}", "red")
            loading_indicator.stop()
            return

        self.spinner_canvas = tk.Canvas(self.main_frame, width=100, height=100)
        self.spinner_canvas.pack(pady=10)
        self.spinner = ExpandingCircle(self.spinner_canvas, 50, 50, 30, 'blue')

        def request_thread():
            try:
                captcha_data = self.get_captcha(session, captcha_id, username)
                if captcha_data:
                    self.executor.submit(self.show_captcha, captcha_data, username, captcha_id)
                # تم عرض الرد من الخادم فقط في get_captcha
            finally:
                # إيقاف السبينر وعناصر التحميل فور استلام أي رد
                loading_indicator.stop()
                self.spinner.stop()
                self.spinner_canvas.pack_forget()

        threading.Thread(target=request_thread).start()

    def get_captcha(self, session, captcha_id, username):
        try:
            captcha_url = f"https://api.ecsc.gov.sy:8080/files/fs/captcha/{captcha_id}"
            while True:
                response = session.get(captcha_url)

                # عرض رد الخادم فقط مهما كان نوع الرد
                self.update_notification(f"Server Response: {response.text}",
                                         "green" if response.status_code == 200 else "red")

                # إرجاع البيانات إذا كان الرد ناجحًا
                if response.status_code == 200:
                    response_data = response.json()
                    return response_data.get("file")
                elif response.status_code == 429:
                    # في حالة تجاوز الحد، نعيد المحاولة
                    time.sleep(0.1)
                elif response.status_code in {401, 403}:
                    # محاولة إعادة تسجيل الدخول في حالة الحاجة
                    if self.login(username, self.accounts[username]["password"], session):
                        continue
                else:
                    # إيقاف التكرار عند أي رد آخر
                    break
        except Exception as e:
            self.update_notification(f"Error: {str(e)}", "red")
        finally:
            # إيقاف جميع عناصر الانتظار عند استلام أي رد من الخادم
            if hasattr(self, 'spinner'):
                self.spinner.stop()
            if hasattr(self, 'spinner_canvas'):
                self.spinner_canvas.pack_forget()
        return None

    def show_captcha(self, captcha_data, username, captcha_id):
        try:
            if self.captcha_frame:
                self.captcha_frame.destroy()
            captcha_base64 = captcha_data.split(",")[1] if "," in captcha_data else captcha_data
            captcha_image_data = np.frombuffer(base64.b64decode(captcha_base64), dtype=np.uint8)
            captcha_image = cv2.imdecode(captcha_image_data, cv2.IMREAD_COLOR)
            if captcha_image is None:
                print("Failed to decode captcha image from memory.")
                return
            start_time = time.time()
            processed_image = self.process_captcha(captcha_image)
            processed_image = cv2.resize(processed_image, (200, 114))
            elapsed_time_bg_removal = time.time() - start_time
            self.display_captcha_image(processed_image)
            start_time = time.time()
            predictions = self.trained_model.predict(processed_image)
            elapsed_time_prediction = time.time() - start_time
            ocr_output_text = f"{predictions[0]} {predictions[1]} {predictions[2]}"
            print(f"Predicted Operation: {ocr_output_text}")
            self.update_notification(f"Captcha solved in {elapsed_time_prediction:.2f}s", "green")
            self.update_time_label(
                f"Background removal: {elapsed_time_bg_removal:.2f}s, Prediction: {elapsed_time_prediction:.2f}s")
            captcha_solution = self.solve_captcha_from_prediction(predictions)
            if captcha_solution is not None:
                self.executor.submit(self.submit_captcha, username, captcha_id, captcha_solution)

            self.spinner.stop()
            self.spinner_canvas.pack_forget()

        except Exception as e:
            self.update_notification(f"Failed to show captcha: {e}", "red", response.txt)
            self.spinner.stop()
            self.spinner_canvas.pack_forget()

    def process_captcha(self, captcha_image):
        if not self.background_images:
            return captcha_image
        best_background = None
        min_diff = float("inf")
        for background in self.background_images:
            background = cv2.resize(background, (captcha_image.shape[1], captcha_image.shape[0]))
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

    def display_captcha_image(self, captcha_image):
        self.captcha_frame = tk.Frame(self.root)
        self.captcha_frame.pack()
        captcha_image_pil = Image.fromarray(cv2.cvtColor(captcha_image, cv2.COLOR_BGR2RGB))
        captcha_image_tk = ImageTk.PhotoImage(captcha_image_pil)
        captcha_label = tk.Label(self.captcha_frame, image=captcha_image_tk)
        captcha_label.image = captcha_image_tk
        captcha_label.grid(row=0, column=0, padx=10, pady=10)

    def remove_background_keep_original_colors(self, captcha_image, background_image):
        # 1. تقليل الدقة لتسريع العملية
        scale_factor = 0.5
        captcha_image = cv2.resize(captcha_image, (0, 0), fx=scale_factor, fy=scale_factor)
        background_image = cv2.resize(background_image, (0, 0), fx=scale_factor, fy=scale_factor)

        # 2. إذا كان GPU مدعومًا، استخدم CUDA لإزالة الخلفية
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            captcha_image_gpu = cv2.cuda_GpuMat()
            background_image_gpu = cv2.cuda_GpuMat()

            captcha_image_gpu.upload(captcha_image)
            background_image_gpu.upload(background_image)

            # حساب الفرق بين الصورتين باستخدام GPU
            diff_gpu = cv2.cuda.absdiff(captcha_image_gpu, background_image_gpu)
            diff = diff_gpu.download()

            # تحويل الفرق إلى صورة رمادية
            gray_gpu = cv2.cuda.cvtColor(diff_gpu, cv2.COLOR_BGR2GRAY)
            gray = gray_gpu.download()

            # تطبيق العتبة (threshold) على الصورة الرمادية
            _, mask = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)

            # رفع القناع إلى GPU
            mask_gpu = cv2.cuda_GpuMat()
            mask_gpu.upload(mask)

            # إزالة الخلفية مع الحفاظ على الألوان الأصلية باستخدام GPU
            result_gpu = cv2.cuda.bitwise_and(captcha_image_gpu, captcha_image_gpu, mask=mask_gpu)
            result = result_gpu.download()

            return result
        else:
            # إذا لم يكن GPU مدعومًا، نستخدم الطريقة العادية
            diff = cv2.absdiff(captcha_image, background_image)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
            result = cv2.bitwise_and(captcha_image, captcha_image, mask=mask)
            return result

    def submit_captcha(self, username, captcha_id, captcha_solution):
        session = self.accounts[username].get("session")
        if not session:
            self.update_notification(f"No session found for user {username}", "red")
            return
        try:
            get_url = f"https://api.ecsc.gov.sy:8080/rs/reserve?id={captcha_id}&captcha={captcha_solution}"
            response = session.get(get_url)
            self.update_notification(f"Server تم التثبيت بنجاح: {response.text}",
                                     "green" if response.status_code == 200 else "red")
        except Exception as e:
            self.update_notification(f"Failed to submit captcha: {e}", "red")

    @staticmethod
    def generate_user_agent():
        user_agent_list = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 11; SM-G996B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.210 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:88.0) Gecko/20100101 Firefox/88.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_2_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.114 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 10; Pixel 3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.101 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.64",
        "Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0",
        "Mozilla/5.0 (Linux; Android 9; SAMSUNG SM-A505FN) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/76.0.3809.111 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 6.1; Trident/7.0; rv:11.0) like Gecko",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; FreeBSD amd64; rv:91.0) Gecko/20100101 Firefox/91.0"
    ]

        return random.choice(user_agent_list)

    def add_account(self):
        username = simpledialog.askstring("Input", "Enter Username:")
        password = simpledialog.askstring("Input", "Enter Password:", show="*")
        if username and password:
            user_agent = self.generate_user_agent()
            session = self.create_session(user_agent)
            start_time = time.time()

            if self.login(username, password, session):
                elapsed_time = time.time() - start_time
                self.update_notification(f"Login successful for user {username}. Time: {elapsed_time:.2f}s", "green")
                self.accounts[username] = {
                    "password": password,
                    "user_agent": user_agent,
                    "session": session,
                    "captcha_id1": None,
                    "captcha_id2": None,
                }

                # إرسال طلب POST لاستخراج المعاملات باستخدام الجلسة الحالية
                process_data = self.fetch_process_ids(session)
                if process_data:
                    self.create_account_ui(username, process_data)
                else:
                    self.update_notification(f"Failed to fetch process IDs for user {username}.", "red")
            else:
                elapsed_time = time.time() - start_time
                self.update_notification(f"Failed to login for user {username}. Time: {elapsed_time:.2f}s", "red")

    def fetch_process_ids(self, session):
        try:
            url = "https://api.ecsc.gov.sy:8080/dbm/db/execute"
            payload = {
                "ALIAS": "OPkUVkYsyq",
                "P_USERNAME": "WebSite",
                "P_PAGE_INDEX": 0,
                "P_PAGE_SIZE": 100
            }
            headers = {
                "Content-Type": "application/json",
                "Alias": "OPkUVkYsyq",
                "Referer": "https://ecsc.gov.sy/requests",
                "Origin": "https://ecsc.gov.sy",
            }

            response = session.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                process_ids = data.get("P_RESULT", [])
                if process_ids:
                    return process_ids
                else:
                    self.update_notification("No process IDs found.", "red")
            else:
                self.update_notification(f"Failed to fetch process IDs. Status code: {response.status_code}", "red")
        except Exception as e:
            self.update_notification(f"Error fetching process IDs: {str(e)}", "red")
        return None

    def create_account_ui(self, username, process_data):
        account_frame = tk.Frame(self.main_frame)
        account_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(account_frame, text=f"Account: {username}").pack(side=tk.LEFT)

        for process in process_data:
            process_id = process.get("PROCESS_ID")
            center_name = process.get("ZCENTER_NAME", "Unknown Center")

            process_frame = tk.Frame(account_frame)
            process_frame.pack(fill=tk.X, padx=10, pady=5)

            # إنشاء زر يحتوي على ZCENTER_NAME مع تصغير حجم الخط
            loading_indicator = ttk.Progressbar(process_frame, mode='indeterminate')

            process_button = tk.Button(process_frame, text=center_name, font=("Helvetica", 10),
                                       command=lambda pid=process_id, indicator=loading_indicator: threading.Thread(
                                           target=self.request_captcha,
                                           args=(username, pid, indicator)
                                       ).start())
            process_button.pack(side=tk.LEFT, padx=8, pady=5)
            loading_indicator.pack(side=tk.LEFT, padx=8, pady=5)

    def request_captcha(self, username, captcha_id, loading_indicator):
        loading_indicator.start()

        session = self.accounts[username].get("session")
        if not session:
            self.update_notification(f"No session found for user {username}", "red")
            loading_indicator.stop()
            return

        self.spinner_canvas = tk.Canvas(self.main_frame, width=100, height=100)
        self.spinner_canvas.pack(pady=10)
        self.spinner = ExpandingCircle(self.spinner_canvas, 50, 50, 30, 'blue')

        def request_thread():
            try:
                captcha_data = self.get_captcha(session, captcha_id, username)
                if captcha_data:
                    self.executor.submit(self.show_captcha, captcha_data, username, captcha_id)
            finally:
                loading_indicator.stop()
                self.spinner.stop()
                self.spinner_canvas.pack_forget()

        threading.Thread(target=request_thread).start()

    def get_captcha(self, session, captcha_id, username):
        try:
            captcha_url = f"https://api.ecsc.gov.sy:8080/files/fs/captcha/{captcha_id}"
            while True:
                response = session.get(captcha_url)

                self.update_notification(f"Server Response: {response.text}",
                                         "green" if response.status_code == 200 else "red")

                if response.status_code == 200:
                    response_data = response.json()
                    return response_data.get("file")
                elif response.status_code == 429:
                    time.sleep(0.1)
                elif response.status_code in {401, 403}:
                    if self.login(username, self.accounts[username]["password"], session):
                        continue
                else:
                    break
        except Exception as e:
            self.update_notification(f"Error: {str(e)}", "red")
        finally:
            if hasattr(self, 'spinner'):
                self.spinner.stop()
            if hasattr(self, 'spinner_canvas'):
                self.spinner_canvas.pack_forget()
        return None

    @staticmethod
    def create_session(user_agent):
        headers = {
            "User-Agent": user_agent,  # تعريف نوع العميل
            "Accept": "application/json, text/plain, */*",  # قبول أنواع المحتوى المختلفة
            "Accept-Language": "ar,en-US;q=0.7,en;q=0.3",  # تحديد اللغات المفضلة
            "Referer": "https://ecsc.gov.sy/login",  # الصفحة الأصلية للطلب
            "Content-Type": "application/json",  # نوع المحتوى المرسل
            "Source": "WEB",  # مصدر الطلب
            "Origin": "https://ecsc.gov.sy",  # المصدر الأساسي للطلب
            "Connection": "keep-alive",  # الحفاظ على الاتصال مفتوحًا لتحسين الأداء
            "Priority": "u=1",  # أولوية عالية (تجريبي)
            "X-Priority": "1",  # أولوية قصوى للطلب
            "Accept-Encoding": "gzip, deflate, br",  # ضغط البيانات لتسريع النقل
            "Cache-Control": "no-cache, no-store, must-revalidate",  # منع التخزين المؤقت لضمان بيانات محدثة
            "X-DNS-Prefetch-Control": "on",  # تحسين زمن الاستجابة عبر جلب DNS مسبقًا
            "TE": "trailers",  # تحسين التعامل مع محتويات الرد
            "Pragma": "no-cache",  # منع التخزين المؤقت على مستوى المتصفح
        }
        session = requests.Session()
        session.headers.update(headers)
        return session
    def login(self, username, password, session, retry_count=3):
        login_url = "https://api.ecsc.gov.sy:8080/secure/auth/login"
        login_data = {"username": username, "password": password}
        for attempt in range(retry_count):
            try:
                post_response = session.post(login_url, json=login_data)
                if post_response.status_code == 200:
                    self.update_notification("Login successful.", "green", post_response.text)
                    return True
                else:
                    self.update_notification(f"Login failed. Status code: {post_response.status_code}",
                                             "red", post_response.text)
                    return False
            except requests.RequestException as e:
                self.update_notification(f"Request error: {e}", "red")
                return False

    def press_cab1_twice(self):
        username = list(self.accounts.keys())[0]
        captcha_id1 = self.accounts[username]["captcha_id1"]

        self.request_captcha(username, captcha_id1, None)
        self.check_server_response(username, captcha_id1, attempt=1)

    def check_server_response(self, username, captcha_id1, attempt):
        session = self.accounts[username].get("session")
        captcha_solution = "123"
        get_url = f"https://api.ecsc.gov.sy:8080/rs/reserve?id={captcha_id1}&captcha={captcha_solution}"

        response = session.get(get_url)
        if response.status_code == 200:
            self.update_notification(f"Response 200 received after attempt {attempt}. Stopping.", "green")
        else:
            self.update_notification(f"Response {response.status_code} after attempt {attempt}.", "red")
            if attempt == 1:
                self.update_notification("Pressing 'cap1' again.", "yellow")
                self.request_captcha(username, captcha_id1, None)
                self.check_server_response(username, captcha_id1, attempt=2)

    def upload_backgrounds(self):
        background_paths = filedialog.askopenfilenames(
            title="Select Background Images", filetypes=[("Image files", "*.jpg *.png *.jpeg")]
        )
        if background_paths:
            self.background_images = [cv2.imread(path) for path in background_paths]
            self.update_notification(f"{len(self.background_images)} background images uploaded successfully!", "green")

    def solve_captcha_from_prediction(self, prediction):
        num1, operation, num2 = prediction
        if operation == "+":
            return num1 + num2
        elif operation == "-":
            return num1 - num2
        elif operation == "×":
            return num1 * num2
        return None

    def update_notification(self, message, color, response_text=None):
        full_message = message
        if response_text:
            full_message += f"\nServer Response: {response_text}"
        self.notification_label.config(text=full_message, bg=color)

        self.root.after(8000, self.clear_notification)

    def clear_notification(self):
        self.notification_label.config(text="", bg="blue")

    def update_time_label(self, message):
        self.time_label.config(text=message)


if __name__ == "__main__":
    root = tk.Tk()
    app = CaptchaApp(root)
    root.mainloop()
