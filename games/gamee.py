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
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException, ElementClickInterceptedException
from datetime import datetime, timedelta
from selenium.webdriver.chrome.service import Service as ChromeService

from claimer import Claimer

class GameeClaimer(Claimer):

    def __init__(self):

        self.settings_file = "variables.txt"
        self.status_file_path = "status.txt"
        self.load_settings()
        self.random_offset = random.randint(self.settings['lowestClaimOffset'], self.settings['highestClaimOffset'])
        self.script = "games/gamee.py"
        self.prefix = "Gamee:"
        self.url = "https://web.telegram.org/k/#@gamee"
        self.pot_full = "Filled"
        self.pot_filling = "Mining"
        self.seed_phrase = None
        self.forceLocalProxy = False
        self.forceRequestUserAgent = False

        super().__init__()

        self.start_app_xpath = "//div[text()='Open app']"

    def launch_iframe(self):
        super().launch_iframe()

        # self.driver.switch_to.default_content()

        # iframe = self.driver.find_element(By.TAG_NAME, "iframe")
        # iframe_url = iframe.get_attribute("src")
        # iframe_url = iframe_url.replace("tgWebAppPlatform=web", "tgWebAppPlatform=android")

        # self.driver.execute_script("arguments[0].src = arguments[1];", iframe, iframe_url)
        # self.driver.execute_script("arguments[0].contentWindow.location.reload();", iframe)
        # WebDriverWait(self.driver, 10).until(EC.frame_to_be_available_and_switch_to_it((By.XPATH, f"//iframe[@src='{iframe_url}']")))

        #self.driver.switch_to.default_content()
        #self.driver.switch_to.frame(iframe)

        # Open tab in main window
        self.driver.switch_to.default_content()
        self.driver.execute_script("location.href = document.querySelector('iframe').src")

    def next_steps(self):
        if self.step:
            pass
        else:
            self.step = "01"

        try:
            self.launch_iframe()
            self.increase_step()

            self.set_cookies()

        except TimeoutException:
            self.output(f"Step {self.step} - Failed to find or switch to the iframe within the timeout period.",1)

        except Exception as e:
            self.output(f"Step {self.step} - An error occurred: {e}",1)

    def full_claim(self):
        self.step = "100"
        self.launch_iframe()

        clicked_it = False

        status_text = ""

        #  # START MINING - clear_overlays provokes move the element to the top of the page and overlap other items
        try:

            xpath = "//div[contains(@class, 'eWLHYP')]" # START MINING button
            button = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            if button:
                button.click()
                self.output(f"Step {self.step} - Successfully clicked 'MINING' button.", 3)
                status_text = "STATUS: Start MINING"

        except TimeoutException:
            try:

                xpath = "//div[contains(@class, 'cYeqKR')]" # MINING button
                button = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                self.output(f"Step {self.step} - Currently mining: {'YES' if button else 'NO'}.", 3)
                status_text = "STATUS: Currently mining" if button else "STATUS: Not mining"

            except TimeoutException:
                self.output(f"Step {self.step} - MINING button NOT found .\n",3)
                status_text = "STATUS: MINING button NOT found"

        self.increase_step()

        # START MINING
        # xpath = "//div[contains(@class, 'eWLHYP')]"
        # xpath = "//div[contains(@class, 'cYeqKR')]"
        # button = self.move_and_click(xpath, 8, False, "click the 'Spin TAB'", self.step, "clickable")
        # if button: button.click()
        # self.increase_step()

        xpath = "//div[contains(@class, 'wxeDq') and .//text()[contains(., 'Spin')]]"
        button = self.move_and_click(xpath, 8, False, "click the 'Spin TAB'", self.step, "clickable")
        if button: button.click()
        self.increase_step()

        # Wait for the 'FREE SPIN' button to appear
        xpath = "//button[.//text()[contains(., 'available')]]"

        while True:

            try:
                button = self.move_and_click(xpath, 30, False, "click the 'FREE Spin'", self.step, "clickable")
                if not button: break
                if button: button.click()
            except TimeoutException:
                break

        self.get_balance(False)

        wait_time = self.get_wait_time(self.step, "pre-claim") 

        if wait_time is None:
            self.output(f"{status_text} - Failed to get wait time. Next try in 60 minutes", 3)
            return 60
        else:
            self.output(f"{status_text} - Next try in {self.show_time(wait_time)}.", 2)
            return wait_time

    def get_balance(self, claimed=False):

        xpath = "//div[contains(@class, 'wxeDq') and .//text()[contains(., 'Mine')]]"
        button = self.move_and_click(xpath, 8, False, "click the 'Mine TAB'", self.step, "clickable")
        if button: button.click()
        self.increase_step()

        self.driver.execute_script("location.href = 'https://prizes.gamee.com/telegram/mining/12'")

        def strip_html_and_non_numeric(text):
            """Remove HTML tags and keep only numeric characters and decimal points."""
            # Remove HTML tags
            clean = re.compile('<.*?>')
            text_without_html = clean.sub('', text)
            # Keep only numeric characters and decimal points
            numeric_text = re.sub(r'[^0-9.]', '', text_without_html)
            return numeric_text

        prefix = "After" if claimed else "Before"
        default_priority = 2 if claimed else 3

        # Dynamically adjust the log priority
        priority = max(self.settings['verboseLevel'], default_priority)

        # Construct the specific balance XPath
        balance_text = f'{prefix} BALANCE:' if claimed else f'{prefix} BALANCE:'
        balance_xpath = "//h2[@id='animated-mining-balance-id']"

        try:
            element = self.monitor_element(balance_xpath)

            # Check if element is not None and process the balance
            if element:
                cleaned_balance = strip_html_and_non_numeric(element)
                self.output(f"Step {self.step} - {balance_text} {cleaned_balance}", priority)

        except NoSuchElementException:
            self.output(f"Step {self.step} - Element containing '{prefix} Balance:' was not found.", priority)
        except Exception as e:
            self.output(f"Step {self.step} - An error occurred: {str(e)}", priority)  # Provide error as string for logging

        # Increment step function, assumed to handle next step logic
        self.increase_step()

    def get_wait_time(self, step_number="108", beforeAfter="pre-claim"):
        try:

            self.output(f"Step {self.step} - check if the timer is elapsing...", 3)

            xpath = "(//p[contains(@class, 'bEEYcp')])[1]"
            actual = float(self.monitor_element(xpath, 15))

            xpath = "(//p[contains(@class, 'bEEYcp')])[2]"
            max = float(self.monitor_element(xpath, 15))

            xpath = "(//p[contains(@class, 'jQUosL')])[1]"
            production = float(self.monitor_element(xpath, 15))

            wait_time = int(((max-actual)/production)*60)

            return wait_time          

        except Exception as e:
            self.output(f"Step {self.step} - An error occurred: {e}", 3)
            if self.settings['debugIsOn']:
                screenshot_path = f"{self.screenshots_path}/{self.step}_get_wait_time_error.png"
                self.driver.save_screenshot(screenshot_path)
                self.output(f"Screenshot saved to {screenshot_path}", 3)

            return None

def main():
    claimer = GameeClaimer()
    claimer.run()

if __name__ == "__main__":
    main()
