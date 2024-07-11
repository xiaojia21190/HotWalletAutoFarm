import os
import shutil
import sys
import time
import re
import json
import getpass
import random
import subprocess
from PIL import Image
from pyzbar.pyzbar import decode
import qrcode_terminal
import fcntl
from fcntl import flock, LOCK_EX, LOCK_UN, LOCK_NB
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException, ElementClickInterceptedException, UnexpectedAlertPresentException
from datetime import datetime, timedelta

def load_settings():
    global settings, settings_file
    default_settings = {
        "forceClaim": False,
        "debugIsOn": False,
        "hideSensitiveInput": True,
        "screenshotQRCode": True,
        "maxSessions": 1,
        "verboseLevel": 2,
        "lowestClaimOffset": 0,
        "highestClaimOffset": 15,
        "forceNewSession": False,
        "useProxy": False,
        "proxyAddress": "http://127.0.0.1:8080"
    }

    if os.path.exists(settings_file):
        with open(settings_file, "r") as f:
            loaded_settings = json.load(f)
        # Filter out unused settings from previous versions
        settings = {k: loaded_settings.get(k, v) for k, v in default_settings.items()}
        output("Settings loaded successfully.", 3)
    else:
        settings = default_settings
        save_settings()

def save_settings():
    global settings, settings_file
    with open(settings_file, "w") as f:
        json.dump(settings, f)
    output("Settings saved successfully.", 3)

def output(string, level):
    if settings['verboseLevel'] >= level:
        print(string)

# Define sessions and settings files
settings_file = "variables.txt"
status_file_path = "status.txt"
settings = {}
load_settings()
driver = None
target_element = None
random_offset = random.randint(settings['lowestClaimOffset'], settings['highestClaimOffset'])
script = "games/vertus.py"
prefix = "Vertus:"
url = "https://web.telegram.org/k/#@vertus_app_bot"

def increase_step():
    global step
    step_int = int(step) + 1
    step = f"{step_int:02}"

print(f"Initialising the {prefix} Wallet Auto-claim Python Script - Good Luck!")

def update_settings():
    global settings

    def update_setting(setting_key, message, default_value):
        current_value = settings.get(setting_key, default_value)
        response = input(f"\n{message} (Y/N, press Enter to keep current [{current_value}]): ").strip().lower()
        if response == "y":
            settings[setting_key] = True
        elif response == "n":
            settings[setting_key] = False

    update_setting("forceClaim", "Shall we force a claim on first run? Does not wait for the timer to be filled", settings["forceClaim"])
    update_setting("debugIsOn", "Should we enable debugging? This will save screenshots in your local drive", settings["debugIsOn"])
    update_setting("hideSensitiveInput", "Should we hide sensitive input? Your phone number and seed phrase will not be visible on the screen", settings["hideSensitiveInput"])
    update_setting("screenshotQRCode", "Shall we allow log in by QR code? The alternative is by phone number and one-time password", settings["screenshotQRCode"])

    try:
        new_max_sessions = int(input(f"\nEnter the number of max concurrent claim sessions. Additional claims will queue until a session slot is free.\n(current: {settings['maxSessions']}): "))
        settings["maxSessions"] = new_max_sessions
    except ValueError:
        output("Number of sessions remains unchanged.", 1)

    try:
        new_verbose_level = int(input("\nEnter the number for how much information you want displaying in the console.\n 3 = all messages, 2 = claim steps, 1 = minimal steps\n(current: {}): ".format(settings['verboseLevel'])))
        if 1 <= new_verbose_level <= 3:
            settings["verboseLevel"] = new_verbose_level
            output("Verbose level updated successfully.", 2)
        else:
            output("Verbose level remains unchanged.", 2)
    except ValueError:
        output("Verbose level remains unchanged.", 2)

    try:
        new_lowest_offset = int(input("\nEnter the lowest possible offset for the claim timer (valid values are -30 to +30 minutes)\n(current: {}): ".format(settings['lowestClaimOffset'])))
        if -30 <= new_lowest_offset <= 30:
            settings["lowestClaimOffset"] = new_lowest_offset
            output("Lowest claim offset updated successfully.", 2)
        else:
            output("Invalid range for lowest claim offset. Please enter a value between -30 and +30.", 2)
    except ValueError:
        output("Lowest claim offset remains unchanged.", 2)

    try:
        new_highest_offset = int(input("\nEnter the highest possible offset for the claim timer (valid values are 0 to 60 minutes)\n(current: {}): ".format(settings['highestClaimOffset'])))
        if 0 <= new_highest_offset <= 60:
            settings["highestClaimOffset"] = new_highest_offset
            output("Highest claim offset updated successfully.", 2)
        else:
            output("Invalid range for highest claim offset. Please enter a value between 0 and 60.", 2)
    except ValueError:
        output("Highest claim offset remains unchanged.", 2)

    if settings["lowestClaimOffset"] > settings["highestClaimOffset"]:
        settings["lowestClaimOffset"] = settings["highestClaimOffset"]
        output("Adjusted lowest claim offset to match the highest as it was greater.", 2)

    update_setting("useProxy", "Use Proxy?", settings["useProxy"])

    if settings["useProxy"]:
        proxy_address = input(f"\nEnter the Proxy IP address and port (current: {settings['proxyAddress']}): ").strip()
        if proxy_address:
            settings["proxyAddress"] = proxy_address

    save_settings()

    update_setting("forceNewSession", "Overwrite existing session and Force New Login? Use this if your saved session has crashed\nOne-Time only (setting not saved): ", settings["forceNewSession"])

    output("\nRevised settings:", 1)
    for key, value in settings.items():
        output(f"{key}: {value}", 1)
    output("", 1)

def get_session_id():
    """Prompts the user for a session ID or determines the next sequential ID based on a 'Wallet' prefix.

    Returns:
        str: The entered session ID or the automatically generated sequential ID.
    """
    global settings, prefix
    output(f"Your session will be prefixed with: {prefix}", 1)
    user_input = input("Enter your unique Session Name here, or hit <enter> for the next sequential wallet: ").strip()

    # Set the directory where session folders are stored
    screenshots_dir = "./screenshots/"

    # Ensure the directory exists to avoid FileNotFoundError
    if not os.path.exists(screenshots_dir):
        os.makedirs(screenshots_dir)

    # List contents of the directory
    try:
        dir_contents = os.listdir(screenshots_dir)
    except Exception as e:
        output(f"Error accessing the directory: {e}", 1)
        return None  # or handle the error differently

    # Filter directories with the 'Wallet' prefix and extract the numeric parts
    wallet_dirs = [int(dir_name.replace(prefix + 'Wallet', ''))
                   for dir_name in dir_contents
                   if dir_name.startswith(prefix + 'Wallet') and dir_name[len(prefix) + 6:].isdigit()]

    # Calculate the next wallet ID
    next_wallet_id = max(wallet_dirs) + 1 if wallet_dirs else 1

    # Use the next sequential wallet ID if no user input was provided
    if not user_input:
        user_input = f"Wallet{next_wallet_id}"  # Ensuring the full ID is prefixed correctly

    return prefix+user_input


# Update the settings based on user input
if len(sys.argv) > 1:
        user_input = sys.argv[1]  # Get session ID from command-line argument
        output(f"Session ID provided: {user_input}",2)
        # Safely check for a second argument
        if len(sys.argv) > 2 and sys.argv[2] == "debug":
            settings['debugIsOn'] = True
else:
    output("\nCurrent settings:",1)
    for key, value in settings.items():
        output(f"{key}: {value}",1)
    user_input = input("\nShould we update our settings? (Default:<enter> / Yes = y): ").strip().lower()
    if user_input == "y":
        update_settings()
    user_input = get_session_id()

session_path = "./selenium/{}".format(user_input)
os.makedirs(session_path, exist_ok=True)
screenshots_path = "./screenshots/{}".format(user_input)
os.makedirs(screenshots_path, exist_ok=True)
backup_path = "./backups/{}".format(user_input)
os.makedirs(backup_path, exist_ok=True)
step = "01"

# Define our base path for debugging screenshots
screenshot_base = os.path.join(screenshots_path, "screenshot")

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument(f"user-data-dir={session_path}")
    chrome_options.add_argument("--headless")  # Ensure headless is enabled
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/124.0.2478.50 Version/17.0 Mobile/15E148 Safari/604.1"
    chrome_options.add_argument(f"user-agent={user_agent}")

    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    if settings["useProxy"]:
        proxy_server = settings["proxyAddress"]
        chrome_options.add_argument(f"--proxy-server={proxy_server}")

    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--test-type")

    chromedriver_path = shutil.which("chromedriver")
    if chromedriver_path is None:
        output("ChromeDriver not found in PATH. Please ensure it is installed.", 1)
        exit(1)

    try:
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        output(f"Initial ChromeDriver setup may have failed: {e}", 1)
        output("Please ensure you have the correct ChromeDriver version for your system.", 1)
        exit(1)

def run_http_proxy():
    proxy_lock_file = "./start_proxy.txt"
    max_wait_time = 15 * 60  # 15 minutes
    wait_interval = 5  # 5 seconds
    start_time = time.time()

    while os.path.exists(proxy_lock_file) and (time.time() - start_time) < max_wait_time:
        output("Proxy is already running. Waiting for it to free up...", 1)
        time.sleep(wait_interval)

    if os.path.exists(proxy_lock_file):
        output("Max wait time elapsed. Proceeding to run the proxy.", 1)

    with open(proxy_lock_file, "w") as lock_file:
        lock_file.write(f"Proxy started at: {time.ctime()}\n")

    try:
        subprocess.run(['./launch.sh', 'enable-proxy'], check=True)
        output("http-proxy started successfully.", 1)
    except subprocess.CalledProcessError as e:
        output(f"Failed to start http-proxy: {e}", 1)
    finally:
        os.remove(proxy_lock_file)

settings["useProxy"] = True
settings["proxyAddress"] = "http://127.0.0.1:8080"

if settings["useProxy"] and settings["proxyAddress"] == "http://127.0.0.1:8080":
    run_http_proxy()
else:
    output("Proxy disabled in settings.",2)

def get_driver():
    global driver
    if driver is None:  # Check if driver needs to be initialized
        manage_session()  # Ensure we can start a session
        driver = setup_driver()
        output("\nCHROME DRIVER INITIALISED: Try not to exit the script before it detaches.",2)
    return driver

def quit_driver():
    global driver
    if driver:
        driver.quit()
        output("\nCHROME DRIVER DETACHED: It is now safe to exit the script.",2)
        driver = None
        release_session()  # Mark the session as closed

def manage_session():
    current_session = session_path
    current_timestamp = int(time.time())
    session_started = False
    new_message = True
    output_priority = 1

    while True:
        try:
            with open(status_file_path, "r+") as file:
                flock(file, LOCK_EX)
                status = json.load(file)

                # Clean up expired sessions
                for session_id, timestamp in list(status.items()):
                    if current_timestamp - timestamp > 300:  # 5 minutes
                        del status[session_id]
                        output(f"Removed expired session: {session_id}", 3)

                # Check for available slots, exclude current session from count
                active_sessions = {k: v for k, v in status.items() if k != current_session}
                if len(active_sessions) < settings['maxSessions']:
                    status[current_session] = current_timestamp
                    file.seek(0)
                    json.dump(status, file)
                    file.truncate()
                    output(f"Session started: {current_session} in {status_file_path}", 3)
                    flock(file, LOCK_UN)
                    session_started = True
                    break
                flock(file, LOCK_UN)

            if not session_started:
                output(f"Waiting for slot. Current sessions: {len(active_sessions)}/{settings['maxSessions']}", output_priority)
                if new_message:
                    new_message = False
                    output_priority = 3
                time.sleep(random.randint(5, 15))
            else:
                break

        except FileNotFoundError:
            # Create file if it doesn't exist
            with open(status_file_path, "w") as file:
                flock(file, LOCK_EX)
                json.dump({}, file)
                flock(file, LOCK_UN)
        except json.decoder.JSONDecodeError:
            # Handle empty or corrupt JSON
            with open(status_file_path, "w") as file:
                flock(file, LOCK_EX)
                output("Corrupted status file. Resetting...", 3)
                json.dump({}, file)
                flock(file, LOCK_UN)

def release_session():
    current_session = session_path
    current_timestamp = int(time.time())

    with open(status_file_path, "r+") as file:
        flock(file, LOCK_EX)
        status = json.load(file)
        if current_session in status:
            del status[current_session]
            file.seek(0)
            json.dump(status, file)
            file.truncate()
        flock(file, LOCK_UN)
        output(f"Session released: {current_session}", 3)
 
def log_into_telegram():
    global driver, target_element, session_path, screenshots_path, backup_path, settings, step
    step = "01"

    def visible_QR_code():
        global driver, screenshots_path, step
        max_attempts = 5
        attempt_count = 0
        last_url = "not a url"  # Placeholder for the last detected QR code URL

        xpath = "//canvas[@class='qr-canvas']"
        driver.get(url)
        wait = WebDriverWait(driver, 30)
        output(f"Step {step} - Waiting for the first QR code - may take up to 30 seconds.", 1)
        increase_step()
        QR_code = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))

        if not QR_code:
            return False

        wait = WebDriverWait(driver, 2)

        while attempt_count < max_attempts:
            try:
                QR_code = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
                QR_code.screenshot(f"{screenshots_path}/Step {step} - Initial QR code.png")
                image = Image.open(f"{screenshots_path}/Step {step} - Initial QR code.png")
                decoded_objects = decode(image)
                if decoded_objects:
                    this_url = decoded_objects[0].data.decode('utf-8')
                    if this_url != last_url:
                        last_url = this_url  # Update the last seen URL
                        attempt_count += 1
                        output("*** Important: Having @HereWalletBot open in your Telegram App might stop this script from logging in! ***\n", 2)
                        output(f"Step {step} - Our screenshot path is {screenshots_path}\n", 1)
                        output(f"Step {step} - Generating screenshot {attempt_count} of {max_attempts}\n", 2)
                        qrcode_terminal.draw(this_url)
                    if attempt_count >= max_attempts:
                        output(f"Step {step} - Max attempts reached with no new QR code.", 1)
                        return False
                    time.sleep(0.5)  # Wait before the next check
                else:
                    time.sleep(0.5)  # No QR code decoded, wait before retrying
            except TimeoutException:
                output(f"Step {step} - QR Code is no longer visible.", 2)
                return True  # Indicates the QR code has been scanned or disappeared
        
        output(f"Step {step} - Failed to generate a valid QR code after multiple attempts.", 1)
        return False  # If loop completes without a successful scan

    driver = get_driver()
    
    # QR Code Method
    if settings['screenshotQRCode']:
        try:

            while True:
                if visible_QR_code():  # QR code not found
                    test_for_2fa()
                    return  # Exit the function entirely

                # If we reach here, it means the QR code is still present:
                choice = input(f"\nStep {step} - QR Code still present. Retry (r) with a new QR code or switch to the OTP method (enter): ")
                print("")
                if choice.lower() == 'r':
                    visible_QR_code()
                else:
                    break

        except TimeoutException:
            output(f"Step {step} - Canvas not found: Restart the script and retry the QR Code or switch to the OTP method.", 1)

    # OTP Login Method
    increase_step()
    output(f"Step {step} - Initiating the One-Time Password (OTP) method...\n",1)
    driver.get(url)
    xpath = "//button[contains(@class, 'btn-primary') and contains(., 'Log in by phone Number')]"
    target_element=move_and_click(xpath, 30, False, "switch to log in by phone number", step, "visible")
    target_element.click()
    increase_step()

    # Country Code Selection
    xpath = "//div[@class='input-field-input']"    
    target_element = move_and_click(xpath, 30, False, "update users country", step, "visible")
    target_element.click()
    user_input = input(f"Step {step} - Please enter your Country Name as it appears in the Telegram list: ").strip()  
    target_element.send_keys(user_input)
    target_element.send_keys(Keys.RETURN)
    increase_step()

    # Phone Number Input
    xpath = "//div[@class='input-field-input' and @inputmode='decimal']"
    target_element = move_and_click(xpath, 30, False, "request users phone number", step, "visible")
    driver.execute_script("arguments[0].click();", target_element)
    def validate_phone_number(phone):
        # Regex for validating an international phone number without leading 0 and typically 7 to 15 digits long
        pattern = re.compile(r"^[1-9][0-9]{6,14}$")
        return pattern.match(phone)

    while True:
        if settings['hideSensitiveInput']:
            user_phone = getpass.getpass(f"Step {step} - Please enter your phone number without leading 0 (hidden input): ")
        else:
            user_phone = input(f"Step {step} - Please enter your phone number without leading 0 (visible input): ")
    
        if validate_phone_number(user_phone):
            output(f"Step {step} - Valid phone number entered.",3)
            break
        else:
            output(f"Step {step} - Invalid phone number, must be 7 to 15 digits long and without leading 0.",1)
    target_element.send_keys(user_phone)
    increase_step()

    # Wait for the "Next" button to be clickable and click it    
    xpath = "//button//span[contains(text(), 'Next')]"
    target_element = move_and_click(xpath, 15, False, "click next to proceed to OTP entry", step, "visible")
    driver.execute_script("arguments[0].click();", target_element)
    increase_step()

    try:
        # Attempt to locate and interact with the OTP field
        wait = WebDriverWait(driver, 20)
        if settings['debugIsOn']:
            time.sleep(3)
            driver.save_screenshot(f"{screenshots_path}/Step {step} - Ready_for_OTP.png")
        password = wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@type='tel']")))
        otp = input(f"Step {step} - What is the Telegram OTP from your app? ")
        password.click()
        password.send_keys(otp)
        output(f"Step {step} - Let's try to log in using your Telegram OTP.\n",3)
        increase_step()

    except TimeoutException:
        # Check for Storage Offline
        xpath = "//button[contains(text(), 'STORAGE_OFFLINE')]"
        target_element = move_and_click(xpath, 8, False, "check for 'STORAGE_OFFLINE'", step, "visible")
        if target_element:
            output(f"Step {step} - ***Progress is blocked by a 'STORAGE_OFFLINE' button",1)
            output(f"Step {step} - If you are re-using an old Wallet session; try to delete or create a new session.",1)
            found_error = True
        # Check for flood wait
        xpath = "//button[contains(text(), 'FLOOD_WAIT')]"
        target_element = move_and_click(xpath, 8, False, "check for 'FLOOD_WAIT'", step, "visible")
        if target_element:
            output(f"Step {step} - ***Progress is blocked by a 'FLOOD_WAIT' button", 1)
            output(f"Step {step} - You need to wait for the specified number of seconds before retrying.", 1)
            output(f"Step {step} - {target_element.text}")
            found_error = True
        if not found_error:
            output(f"Step {step} - Selenium was unable to interact with the OTP screen for an unknown reason.")

    except Exception as e:  # Catch any other unexpected errors
        output(f"Step {step} - Login failed. Error: {e}", 1) 
        if settings['debugIsOn']:
            driver.save_screenshot(f"{screenshots_path}/Step {step} - error_Something_Occured.png")

    increase_step()
    test_for_2fa()

    if settings['debugIsOn']:
        time.sleep(3)
        driver.save_screenshot(f"{screenshots_path}/Step {step} - After_Entering_OTP.png")

def test_for_2fa():
    global settings, driver, screenshots_path, step
    try:
        increase_step()
        WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        xpath = "//input[@type='password' and contains(@class, 'input-field-input')]"
        fa_input = move_and_click(xpath, 10, False, "check for 2FA requirement (will timeout if you don't have 2FA)", step, "present")
        if fa_input:
            if settings['hideSensitiveInput']:
                tg_password = getpass.getpass(f"Step {step} - Enter your Telegram 2FA password: ")
            else:
                tg_password = input(f"Step {step} - Enter your Telegram 2FA password: ")
            fa_input.send_keys(tg_password + Keys.RETURN)
            output(f"Step {step} - 2FA password sent.\n", 3)
            output(f"Step {step} - Checking if the 2FA password is correct.\n", 2)
            xpath = "//*[contains(text(), 'Incorrect password')]"
            try:
                incorrect_password = WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.XPATH, xpath)))
                output(f"Step {step} - 2FA password is marked as incorrect by Telegram - check your debug screenshot if active.", 1)
                if settings['debugIsOn']:
                    screenshot_path = f"{screenshots_path}/Step {step} - Test QR code after session is resumed.png"
                    driver.save_screenshot(screenshot_path)
                quit_driver()
                sys.exit()  # Exit if incorrect password is detected
            except TimeoutException:
                pass

            output(f"Step {step} - No password error found.", 3)
            xpath = "//input[@type='password' and contains(@class, 'input-field-input')]"
            fa_input = move_and_click(xpath, 5, False, "final check to make sure we are correctly logged in", step, "present")
            if fa_input:
                output(f"Step {step} - 2FA password entry is still showing, check your debug screenshots for further information.\n", 1)
                sys.exit()
            output(f"Step {step} - 2FA password check appears to have passed OK.\n", 3)
        else:
            output(f"Step {step} - 2FA input field not found.\n", 1)

    except TimeoutException:
        # 2FA field not found
        output(f"Step {step} - Two-factor Authorization not required.\n", 3)

    except Exception as e:  # Catch any other unexpected errors
        output(f"Step {step} - Login failed. 2FA Error - you'll probably need to restart the script: {e}", 1)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/Step {step} - error: Something Bad Occured.png"
            driver.save_screenshot(screenshot_path)

def next_steps():
    driver = get_driver()
    cookies_path = f"{session_path}/cookies.json"
    cookies = driver.get_cookies()
    with open(cookies_path, 'w') as file:
        json.dump(cookies, file)

def launch_iframe():
    global driver, target_element, settings, step
    driver = get_driver()

    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        output(f"Step {step} - Attempting to verify if we are logged in (hopefully QR code is not present).",3)
        xpath = "//canvas[@class='qr-canvas']"
        wait = WebDriverWait(driver, 5)
        wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/Step {step} - Test QR code after session is resumed.png"
            driver.save_screenshot(screenshot_path)
        output(f"Step {step} - Chrome driver reports the QR code is visible: It appears we are no longer logged in.",2)
        output(f"Step {step} - Most likely you will get a warning that the central input box is not found.",2)
        output(f"Step {step} - System will try to restore session, or restart the script from CLI force a fresh log in.\n",2)

    except TimeoutException:
        output(f"Step {step} - nothing found to action. The QR code test passed.\n",3)
    increase_step()

    driver.get(url)
    WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')

    # There is a very unlikely scenario that the chat might have been cleared.
    # In this case, the "START" button needs pressing to expose the chat window!
    xpath = "//button[contains(., 'START')]"
    button = move_and_click(xpath, 8, False, "check for the start button (should not be present)", step, "visible")
    if button:
        button.click()
    increase_step()


    # New link logic to avoid finding and expired link
    if find_working_link(step):
        increase_step()
    else:
        send_start(step)
        increase_step()
        find_working_link(step)
        increase_step()

    # Now let's move to and JS click the "Launch" Button
    xpath = "//button[contains(@class, 'popup-button') and contains(., 'Launch')]"
    button = move_and_click(xpath, 8, False, "click the 'Launch' button", step, "visible")
    if button:
        button.click()
    increase_step()

    # HereWalletBot Pop-up Handling
    select_iframe(step)
    increase_step()

def click_element(xpath, timeout=30):
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            element = driver.find_element(By.XPATH, xpath)
            # Ensure the element is in the viewport
            driver.execute_script("arguments[0].scrollIntoView();", element)
            
            # Clear any potential overlays before attempting to click
            overlays_cleared = clear_overlays(element, step)
            if overlays_cleared is None:
                overlays_cleared = 0

            if overlays_cleared > 0:
                output(f"Step {step} - Cleared {overlays_cleared} overlay(s), retrying click...", 3)

            # Attempt to click the element
            element.click()
            return True  # Success on clicking the element
        except ElementClickInterceptedException as e:
            # If still intercepted, try to hide the intercepting element directly
            intercepting_element = driver.execute_script(
                "var elem = arguments[0];"
                "var rect = elem.getBoundingClientRect();"
                "var x = rect.left + (rect.width / 2);"
                "var y = rect.top + (rect.height / 2);"
                "return document.elementFromPoint(x, y);", element)
            if intercepting_element:
                driver.execute_script("arguments[0].style.display = 'none';", intercepting_element)
                output(f"Step {step} - Intercepting element hidden, retrying click...", 3)
        except UnexpectedAlertPresentException:
            # Handle unexpected alert during the click
            alert = driver.switch_to.alert
            alert_text = alert.text
            alert.accept()  # Accept the alert or modify if you need to dismiss or interact differently
            output(f"Step {step} - Unexpected alert handled: {alert_text}", 3)
        except (StaleElementReferenceException, NoSuchElementException):
            pass  # Element not found or stale, try again
        except TimeoutException:
            output(f"Step {step} - Click timed out.", 2)
            break  # Exit loop if timed out
        except Exception as e:
            output(f"Step {step} - An error occurred:", 3)
            break  # Exit loop on unexpected error
    return False  # Return False if the element could not be clicked

def full_claim():
    global driver, target_element, settings, session_path, step, random_offset
    step = "100"

    def check_daily_reward():
        action = ActionChains(driver)
        
        # Select the 'Missions' link and click it
        mission_xpath = "//p[contains(text(), 'Missions')]"
        move_and_click(mission_xpath, 10, False, "move to the missions link", step, "visible")
        success = click_element(mission_xpath)
        if success:
            output(f"Step {step} - Successfully able to click the 'Missions' link.",3)
        else:
            output(f"Step {step} - Failed to click the 'Missions' link.",3)
        
        # Select the 'Daily' link and click it
        daily_xpath = "//p[contains(text(), 'Daily')]"
        move_and_click(daily_xpath, 10, False, "move to the daily missions link", step, "visible")
        button = move_and_click(daily_xpath, 10, False, "move to the daily missions link", step, "visible")
        success = click_element(daily_xpath)
        if success:
            output(f"Step {step} - Successfully able to click the 'Daily Missions' link.",3)
        else:
            output(f"Step {step} - Failed to click the 'Daily Missions' link.",3)
        increase_step()
        
        # Try to select and click the 'Claim' link
        claim_xpath = "//p[contains(text(), 'Claim')]"
        button = move_and_click(claim_xpath, 10, False, "move to the claim daily missions link", step, "visible")
        if button:
            driver.execute_script("arguments[0].click();", button)
        success = click_element(claim_xpath)
        if success:
            increase_step()
            output(f"Step {step} - Successfully able to click the 'Claim Daily' link.",3)
            return "Daily bonus claimed."
        
        # Check if the 'Come back tomorrow' message is visible
        come_back_tomorrow_xpath = "//p[contains(text(), 'Come back tomorrow')]"
        come_back_tomorrow_msg = move_and_click(come_back_tomorrow_xpath, 10, False, "check if the bonus is for tomorrow", step, "visible")
        if come_back_tomorrow_msg:
            increase_step()
            return "The daily bonus will be available tomorrow."
        
        # If no condition is met, return a default message
        increase_step()
        return "Daily bonus status unknown."

    def apply_random_offset(unmodifiedTimer):
        global settings, step, random_offset
        if settings['lowestClaimOffset'] <= settings['highestClaimOffset']:
            random_offset = random.randint(settings['lowestClaimOffset'], settings['highestClaimOffset'])
            modifiedTimer = unmodifiedTimer + random_offset
            output(f"Step {step} - Random offset applied to the wait timer of: {random_offset} minutes.", 2)
            return modifiedTimer

    launch_iframe()

    xpath = "//p[text()='Collect']"
    island_text = ""
    success = click_element(xpath)
    if success:
        output(f"Step {step} - We clicked the reward button for the Island Claim.",3)
        island_text = "Island bonus claimed. "
    increase_step()

    # Click on the Storage link:
    xpath = "//p[text()='Mining']"
    success = click_element(xpath)
    increase_step()

    try:
        element = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//p[contains(text(), 'VERT Balance:')]/following-sibling::div/p[@class='_value_1jcpd_16']")
            )
        )

        # Retrieve the text content of the balance element
        if element is not None:
            balance_part = element.text.strip()  # Get the text content and strip any leading/trailing whitespace
            output(f"Step {step} - VERT balance prior to claim: {balance_part}", 3)

    except NoSuchElementException:
        output(f"Step {step} - Element containing 'VERT Balance:' was not found.", 3)
    except Exception as e:
        print(f"Step {step} - An error occurred:", e)
    increase_step()

    wait_time_text = get_wait_time(step, "pre-claim") 
    output(f"Step {step} - Pre-Claim raw wait time text: {wait_time_text}",3)

    if wait_time_text != "Ready to collect":
        matches = re.findall(r'(\d+)([hm])', wait_time_text)
        remaining_wait_time = (sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches)) + random_offset
        if remaining_wait_time < 5 or settings["forceClaim"]:
            settings['forceClaim'] = True
            output(f"Step {step} - the remaining time to claim is less than the random offset, so applying: settings['forceClaim'] = True", 3)
        else:
            remaining_wait_time = min (180, remaining_wait_time)
            output(f"STATUS: {island_text}We'll go back to sleep for {remaining_wait_time} minutes.", 1)
            return remaining_wait_time

    if wait_time_text == "Unknown":
      return 15

    try:
        output(f"Step {step} - The pre-claim wait time is : {wait_time_text} and random offset is {random_offset} minutes.",1)
        increase_step()

        if wait_time_text == "Ready to collect" or settings['forceClaim']:
            try:
                xpath = "//div[p[text()='Collect']]"
                success = click_element(xpath)
                if success:
                    output(f"Step {step} - We successfully clicked the Collect button.",2)
                else:
                    output(f"Step {step} - We failed to the Collect button.",2)

                xpath = "//p[contains(@class, '_text_16x1w_17') and text()='Claim']"
                success = click_element(xpath)
                if success:
                    output(f"Step {step} Successfully Claimed The new splash from vertus :) ", 2)
                else:
                    output(f"Step {step} Failed to click 'the newest Claim' button", 2)
                increase_step()

                time.sleep(5)

                wait_time_text = get_wait_time(step, "post-claim") 
                output(f"Step {step} - Post-Claim raw wait time text: {wait_time_text}",3)
                matches = re.findall(r'(\d+)([hm])', wait_time_text)
                total_wait_time = apply_random_offset(sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches))
                increase_step()

                try:
                    element = WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located(
                            (By.XPATH, "//p[contains(text(), 'VERT Balance:')]/following-sibling::div/p")
                        )
                    )

                    # Retrieve the text content of the balance element
                    if element is not None:
                        balance_part = element.text.strip()  # Get the text content and strip any leading/trailing whitespace
                        output(f"Step {step} - post claim Vert BALANCE: {balance_part}", 2)

                except NoSuchElementException:
                    output(f"Step {step} - Element containing 'VERT Balance:' was not found.", 3)
                except Exception as e:
                    print(f"Step {step} - An error occurred:", e)
                increase_step()

                # Get the daily reward
                daily_reward_text = check_daily_reward()
                increase_step()
                
                if wait_time_text == "Ready to collect":
                    output(f"STATUS: The wait timer is still showing: Filled.",1)
                    output(f"Step {step} - This means either the claim failed, or there is >4 minutes lag in the game.",1)
                    output(f"Step {step} - We'll check back in 1 hour to see if the claim processed and if not try again.",2)
                else:
                    output(f"STATUS: {island_text}. Successful Claim & {daily_reward_text}: Next claim in {min(60, total_wait_time)} minutes.",1)
                return min(180, total_wait_time)

            except TimeoutException:
                output(f"STATUS: The claim process timed out: Maybe the site has lag? Will retry after one hour.",1)
                return 60
            except Exception as e:
                output(f"STATUS: An error occurred while trying to claim: {e}\nLet's wait an hour and try again",1)
                return 60

        else:
            # If the wallet isn't ready to be claimed, calculate wait time based on the timer provided on the page
            matches = re.findall(r'(\d+)([hm])', wait_time_text)
            if matches:
                total_time = sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches)
                total_time += 1
                total_time = max(5, total_time) # Wait at least 5 minutes or the time
                output(f"Step {step} - Not Time to claim this wallet yet. Wait for {total_time} minutes until the storage is filled.",2)
                return total_time 
            else:
                output(f"Step {step} - No wait time data found? Let's check again in one hour.",2)
                return 60  # Default wait time when no specific time until filled is found.
    except Exception as e:
        output(f"Step {step} - An unexpected error occurred: {e}",1)
        return 60  # Default wait time in case of an unexpected error

def monitor_element(xpath, timeout=8):
    end_time = time.time() + timeout
    first_time = True
    while time.time() < end_time:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            # Debugging: Output the number of elements found
            if first_time:
                output(f"Step {step} - Found {len(elements)} elements with XPath: {xpath}", 3)
                first_time = False

            # Check if any elements were found
            if elements:
                # Get the text content of the first relevant div element
                for element in elements:
                    if element.text.strip() != "":
                        cleaned_text = element.text.replace('\n', ' ').replace('\r', ' ').strip()
                        return cleaned_text

        except (StaleElementReferenceException, TimeoutException, NoSuchElementException):
            pass
        except Exception as e:
            output(f"An error occurred: {e}", 3)
    return "Unknown"
        
def get_wait_time(step_number="108", beforeAfter="pre-claim", max_attempts=2):
    for attempt in range(1, max_attempts + 1):
        try:
            xpath = "//p[contains(@class, 'descInfo')][1]"
            move_and_click(xpath, 10, False, f"get the {beforeAfter} wait timer", step, "visible")
            wait_time_element = monitor_element(xpath,10)
            
            # Check if wait_time_element is not None and return its text
            if wait_time_element is not None:
                return wait_time_element
            else:
                output(f"Step {step_number} - Attempt {attempt}: Wait time element not found. Clicking the 'Storage' link and retrying...", 3)
                storage_xpath = "//h4[text()='Storage']"
                move_and_click(storage_xpath, 30, True, "click the 'storage' link", f"{step_number} recheck", "clickable")
                output(f"Step {step_number} - Attempted to select storage again...", 3)

        except TimeoutException:
            if attempt < max_attempts:  # Attempt failed, but retries remain
                output(f"Step {step_number} - Attempt {attempt}: Wait time element not found. Clicking the 'Storage' link and retrying...", 3)
                storage_xpath = "//h4[text()='Storage']"
                move_and_click(storage_xpath, 30, True, "click the 'storage' link", f"{step_number} recheck", "clickable")
            else:  # No retries left after initial failure
                output(f"Step {step_number} - Attempt {attempt}: Wait time element not found.", 3)

        except Exception as e:
            output(f"Step {step_number} - An error occurred on attempt {attempt}: {e}", 3)

    # If all attempts fail         
    return "Unknown"

def clear_screen():
    # Attempt to clear the screen after entering the seed phrase or mobile phone number.
    # For Windows
    if os.name == 'nt':
        os.system('cls')
    # For macOS and Linux
    else:
        os.system('clear')

def select_iframe(old_step):
    global driver, screenshots_path, settings, step
    output(f"Step {step} - Attempting to switch to the app's iFrame...",2)

    try:
        wait = WebDriverWait(driver, 20)
        popup_body = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "popup-body")))
        iframe = popup_body.find_element(By.TAG_NAME, "iframe")
        driver.switch_to.frame(iframe)
        output(f"Step {step} - Was successfully able to switch to the app's iFrame.\n",3)

        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-iframe-switched.png"
            driver.save_screenshot(screenshot_path)

    except TimeoutException:
        output(f"Step {step} - Failed to find or switch to the iframe within the timeout period.\n",3)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-iframe-timeout.png"
            driver.save_screenshot(screenshot_path)
    except Exception as e:
        output(f"Step {step} - An error occurred while attempting to switch to the iframe: {e}\n",3)
        if settings['debugIsOn']:
            screenshot_pat,h = f"{screenshots_path}/{step}-iframe-error.png"
            driver.save_screenshot(screenshot_path)

def find_working_link(old_step):
    global driver, screenshots_path, settings, step
    output(f"Step {step} - Attempting to open a link for the app...",2)

    start_app_xpath = "//button//span[text()='Open app']"
    try:
        start_app_buttons = WebDriverWait(driver, 5).until(EC.presence_of_all_elements_located((By.XPATH, start_app_xpath)))
        clicked = False

        for button in reversed(start_app_buttons):
            actions = ActionChains(driver)
            actions.move_to_element(button).pause(0.2)
            try:
                if settings['debugIsOn']:
                    driver.save_screenshot(f"{screenshots_path}/{step} - Find working link.png".format(screenshots_path))
                actions.perform()
                driver.execute_script("arguments[0].click();", button)
                clicked = True
                break
            except StaleElementReferenceException:
                continue
            except ElementClickInterceptedException:
                continue

        if not clicked:
            output(f"Step {step} - None of the 'Open Wallet' buttons were clickable.\n",1)
            if settings['debugIsOn']:
                screenshot_path = f"{screenshots_path}/{step}-no-clickable-button.png"
                driver.save_screenshot(screenshot_path)
            return False
        else:
            output(f"Step {step} - Successfully able to open a link for the app..\n",3)
            if settings['debugIsOn']:
                screenshot_path = f"{screenshots_path}/{step}-app-opened.png"
                driver.save_screenshot(screenshot_path)
            return True

    except TimeoutException:
        output(f"Step {step} - Failed to find the 'Open Wallet' button within the expected timeframe.\n",1)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-timeout-finding-button.png"
            driver.save_screenshot(screenshot_path)
        return False
    except Exception as e:
        output(f"Step {step} - An error occurred while trying to open the app: {e}\n",1)
        if settings['debugIsOn']:
            screenshot_path = f"{screenshots_path}/{step}-unexpected-error-opening-app.png"
            driver.save_screenshot(screenshot_path)
        return False


def send_start(old_step):
    global driver, screenshots_path, backup_path, settings, step
    xpath = "//div[contains(@class, 'input-message-container')]/div[contains(@class, 'input-message-input')][1]"
    
    def attempt_send_start():
        global backup_path
        chat_input = move_and_click(xpath, 5, False, "find the chat window/message input box", step, "present")
        if chat_input:
            increase_step()
            output(f"Step {step} - Attempting to send the '/start' command...",2)
            chat_input.send_keys("/start")
            chat_input.send_keys(Keys.RETURN)
            output(f"Step {step} - Successfully sent the '/start' command.\n",3)
            if settings['debugIsOn']:
                screenshot_path = f"{screenshots_path}/{step}-sent-start.png"
                driver.save_screenshot(screenshot_path)
            return True
        else:
            output(f"Step {step} - Failed to find the message input box.\n",1)
            return False

    if not attempt_send_start():
        # Attempt failed, try restoring from backup and retry
        output(f"Step {step} - Attempting to restore from backup and retry.\n",2)
        if restore_from_backup(backup_path):
            if not attempt_send_start():  # Retry after restoring backup
                output(f"Step {step} - Retried after restoring backup, but still failed to send the '/start' command.\n",1)
        else:
            output(f"Step {step} - Backup restoration failed or backup directory does not exist.\n",1)

def restore_from_backup(path):
    global step, session_path
    if os.path.exists(path):
        try:
            quit_driver()
            shutil.rmtree(session_path)
            shutil.copytree(path, session_path, dirs_exist_ok=True)
            driver = get_driver()
            driver.get(url)
            WebDriverWait(driver, 10).until(lambda d: d.execute_script('return document.readyState') == 'complete')
            output(f"Step {step} - Backup restored successfully.",2)
            return True
        except Exception as e:
            output(f"Step {step} - Error restoring backup: {e}\n",1)
            return False
    else:
        output(f"Step {step} - Backup directory does not exist.\n",1)
        return False

def move_and_click(xpath, wait_time, click, action_description, old_step, expectedCondition):
    global driver, screenshots_path, settings, step
    target_element = None

    def timer():
        return random.randint(1, 3) / 10

    def offset():
        return random.randint(1, 5)

    def handle_alert():
        try:
            while True:
                alert = driver.switch_to.alert
                alert_text = alert.text
                alert.accept()  # or alert.dismiss() if you need to dismiss it
                output(f"STATUS: Alert handled: {alert_text}", 1)
        except:
            pass

    output(f"Step {step} - Attempting to {action_description}...", 2)

    try:
        wait = WebDriverWait(driver, wait_time)
        # Check and prepare the element based on the expected condition
        if expectedCondition == "visible":
            target_element = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
        elif expectedCondition == "present":
            target_element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        elif expectedCondition == "invisible":
            wait.until(EC.invisibility_of_element_located((By.XPATH, xpath)))
            return None  # Early return as there's no element to interact with
        elif expectedCondition == "clickable":
            target_element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))

        # Check if the target_element is found
        if target_element is None:
            output(f"Step {step} - The element was not found for {action_description}.", 2)
            return None

        # Before interacting, check for and remove overlays if click is needed or visibility is essential
        if expectedCondition in ["visible", "clickable"]:
            clear_overlays(target_element, step)

        # Perform actions if the element is found and clicking is requested
        if target_element:
            if expectedCondition == "clickable":
                actions = ActionChains(driver)
                actions.move_by_offset(0, 0 - offset()) \
                        .pause(timer()) \
                        .move_by_offset(0, offset()) \
                        .pause(timer()) \
                        .move_to_element(target_element) \
                        .pause(timer()) \
                        .perform()
                output(f"Step {step} - Successfully moved to the element using ActionChains.", 3)
            if click:
                click_element(xpath, wait_time)
        
        # Continuously handle alerts throughout the process
        handle_alert()

        return target_element

    except UnexpectedAlertPresentException as e:
        handle_alert()

    except TimeoutException:
        output(f"Step {step} - Timeout while trying to {action_description}.", 3)
        if settings['debugIsOn']:
            # Capture the page source and save it to a file
            page_source = driver.page_source
            with open(f"{screenshots_path}/{step}_page_source.html", "w", encoding="utf-8") as f:
                f.write(page_source)
            logs = driver.get_log("browser")
            with open(f"{screenshots_path}/{step}_browser_console_logs.txt", "w", encoding="utf-8") as f:
                for log in logs:
                    f.write(f"{log['level']}: {log['message']}\n")

    except StaleElementReferenceException:
        output(f"Step {step} - StaleElementReferenceException caught for {action_description}.", 2)

    except Exception as e:
        output(f"Step {step} - An error occurred while trying to {action_description}, or maybe we got a success message.", 1)

    finally:
        # Check and handle any remaining alerts before finishing
        handle_alert()
        if settings['debugIsOn']:
            time.sleep(5)
            screenshot_path = f"{screenshots_path}/{step}-{action_description}.png"
            driver.save_screenshot(screenshot_path)
        return target_element

def clear_overlays(target_element, step):
    try:
        # Get the location of the target element
        element_location = target_element.location_once_scrolled_into_view
        overlays = driver.find_elements(By.XPATH, "//*[contains(@style,'position: absolute') or contains(@style,'position: fixed')]")
        overlays_cleared = 0
        for overlay in overlays:
            overlay_rect = overlay.rect
            # Check if overlay covers the target element
            if (overlay_rect['x'] <= element_location['x'] <= overlay_rect['x'] + overlay_rect['width'] and
                overlay_rect['y'] <= element_location['y'] <= overlay_rect['y'] + overlay_rect['height']):
                driver.execute_script("arguments[0].style.display = 'none';", overlay)
                overlays_cleared += 1
        output(f"Step {step} - Removed {overlays_cleared} overlay(s) covering the target.", 3)
        return overlays_cleared
    except Exception as e:
        output(f"Step {step} - An error occurred while trying to clear overlays: {e}", 1)
        return 0

def validate_seed_phrase():
    # Let's take the user inputed seed phrase and carry out basic validation
    while True:
        # Prompt the user for their seed phrase
        if settings['hideSensitiveInput']:
            seed_phrase = getpass.getpass(f"Step {step} - Please enter your 12-word seed phrase (your input is hidden): ")
        else:
            seed_phrase = input(f"Step {step} - Please enter your 12-word seed phrase (your input is visible): ")
        try:
            if not seed_phrase:
              raise ValueError(f"Step {step} - Seed phrase cannot be empty.")

            words = seed_phrase.split()
            if len(words) != 12:
                raise ValueError(f"Step {step} - Seed phrase must contain exactly 12 words.")

            pattern = r"^[a-z ]+$"
            if not all(re.match(pattern, word) for word in words):
                raise ValueError(f"Step {step} - Seed phrase can only contain lowercase letters and spaces.")
            return seed_phrase  # Return if valid

        except ValueError as e:
            output(f"Error: {e}",1)

# Start a new PM2 process
def start_pm2_app(script_path, app_name, session_name):
    interpreter_path = "venv/bin/python3"
    command = f"NODE_NO_WARNINGS=1 pm2 start {script_path} --name {app_name} --interpreter {interpreter_path} --watch {script_path} -- {session_name}"
    subprocess.run(command, shell=True, check=True)

# List all PM2 processes
def save_pm2():
    command = f"NODE_NO_WARNINGS=1 pm2 save"
    result = subprocess.run(command, shell=True, text=True, capture_output=True)
    print(result.stdout)

def backup_telegram():
    global session_path, step

    # Ask the user if they want to backup their Telegram directory
    backup_prompt = input("Would you like to backup your Telegram directory? (Y/n): ").strip().lower()
    if backup_prompt == 'n':
        output(f"Step {step} - Backup skipped by user choice.", 3)
        return

    # Ask the user for a custom filename
    custom_filename = input("Enter a custom filename for the backup (leave blank for default): ").strip()

    # Define the backup destination path
    if custom_filename:
        backup_directory = os.path.join(os.path.dirname(session_path), f"Telegram:{custom_filename}")
    else:
        backup_directory = os.path.join(os.path.dirname(session_path), "Telegram")

    try:
        # Ensure the backup directory exists and copy the contents
        if not os.path.exists(backup_directory):
            os.makedirs(backup_directory)
        shutil.copytree(session_path, backup_directory, dirs_exist_ok=True)
        output(f"Step {step} - We backed up the session data in case of a later crash!", 3)
    except Exception as e:
        output(f"Step {step} - Oops, we weren't able to make a backup of the session data! Error: {e}", 1)

def main():
    global session_path, settings, step
    if not settings["forceNewSession"]:
        load_settings()
    cookies_path = os.path.join(session_path, 'cookies.json')
    if os.path.exists(cookies_path) and not settings['forceNewSession']:
        output("Resuming the previous session...",2)
    else:
        telegram_backup_dirs = [d for d in os.listdir(os.path.dirname(session_path)) if d.startswith("Telegram")]
        if telegram_backup_dirs:
            print("Previous Telegram login sessions found. Pressing <enter> will select the account numbered '1':")
            for i, dir_name in enumerate(telegram_backup_dirs):
                print(f"{i + 1}. {dir_name}")
    
            user_input = input("Enter the number of the session you want to restore, or 'n' to create a new session: ").strip().lower()
    
            if user_input == 'n':
                log_into_telegram()
                quit_driver()
                backup_telegram()
            elif user_input.isdigit() and 0 < int(user_input) <= len(telegram_backup_dirs):
                restore_from_backup(os.path.join(os.path.dirname(session_path), telegram_backup_dirs[int(user_input) - 1]))
            else:
                restore_from_backup(os.path.join(os.path.dirname(session_path), telegram_backup_dirs[0]))  # Default to the first session

        else:
            log_into_telegram()
            quit_driver()
            backup_telegram()

        next_steps()
        quit_driver()

        try:
            shutil.copytree(session_path, backup_path, dirs_exist_ok=True)
            output("We backed up the session data in case of a later crash!",3)
        except Exception as e:
            output("Oops, we weren't able to make a backup of the session data! Error:", 1)

        pm2_session = session_path.replace("./selenium/", "")
        output(f"You could add the new/updated session to PM use: pm2 start {script} --interpreter venv/bin/python3 --name {pm2_session} -- {pm2_session}",1)
        user_choice = input("Enter 'y' to continue to 'claim' function, 'e' to exit, 'a' or <enter> to automatically add to PM2: ").lower()

        if user_choice == "e":
            output("Exiting script. You can resume the process later.", 1)
            sys.exit()
        elif user_choice == "a" or not user_choice:
            start_pm2_app(script, pm2_session, pm2_session)
            user_choice = input("Should we save your PM2 processes? (Y/n): ").lower()
            if user_choice == "y" or not user_choice:
                save_pm2()
            output(f"You can now watch the session log into PM2 with: pm2 logs {pm2_session}", 2)
            sys.exit()

    while True:
        manage_session()
        wait_time = full_claim()

        if os.path.exists(status_file_path):
            with open(status_file_path, "r+") as file:
                status = json.load(file)
                if session_path in status:
                    del status[session_path]
                    file.seek(0)
                    json.dump(status, file)
                    file.truncate()
                    output(f"Session released: {session_path}",3)

        quit_driver()
                
        now = datetime.now()
        next_claim_time = now + timedelta(minutes=wait_time)
        this_claim_str = now.strftime("%d %B - %H:%M")
        next_claim_time_str = next_claim_time.strftime("%d %B - %H:%M")
        output(f"{this_claim_str} | Need to wait until {next_claim_time_str} before the next claim attempt. Approximately {wait_time} minutes.", 1)
        if settings["forceClaim"]:
            settings["forceClaim"] = False

        while wait_time > 0:
            this_wait = min(wait_time, 15)
            now = datetime.now()
            timestamp = now.strftime("%H:%M")
            output(f"[{timestamp}] Waiting for {this_wait} more minutes...",3)
            time.sleep(this_wait * 60)  # Convert minutes to seconds
            wait_time -= this_wait
            if wait_time > 0:
                output(f"Updated wait time: {wait_time} minutes left.",3)


if __name__ == "__main__":
    main()
