import os
import shutil
import sys
import time
import re
import json
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

class HotClaimer(Claimer):

    def __init__(self):
        self.settings_file = "variables.txt"
        self.status_file_path = "status.txt"
        self.load_settings()
        self.random_offset = random.randint(self.settings['lowestClaimOffset'], self.settings['highestClaimOffset'])
        self.script = "games/hot.py"
        self.prefix = "HOT:"
        self.url = "https://web.telegram.org/k/#@herewalletbot"
        self.pot_full = "Filled"
        self.pot_filling = "to fill"
        self.seed_phrase = None
        self.forceLocalProxy = False
        self.forceRequestUserAgent = False
        self.step = "01"
        self.imported_seedphrase = None

        super().__init__()

        self.start_app_xpath = "//a[@href='https://t.me/herewalletbot/app']"

    def next_steps(self):
        try:
            self.launch_iframe()
            self.increase_step()

            xpath = "//button[p[contains(text(), 'Log in')]]"
            target_element = self.move_and_click(xpath, 30, False, "find the HereWallet log-in button", "08", "visible")
            self.driver.execute_script("arguments[0].click();", target_element)
            self.increase_step()

            xpath = "//p[contains(text(), 'Seed or private key')]/ancestor-or-self::*/textarea"
            input_field = self.move_and_click(xpath, 30, True, "locate seedphrase textbox", self.step, "clickable")
            if not self.imported_seedphrase:
                self.imported_seedphrase = self.validate_seed_phrase()
            input_field.send_keys(self.imported_seedphrase) 
            self.output(f"Step {self.step} - Was successfully able to enter the seed phrase...", 3)
            self.increase_step()

            xpath = "//button[contains(text(), 'Continue')]"
            self.move_and_click(xpath, 30, True, "click continue after seedphrase entry", self.step, "clickable")
            self.increase_step()

            xpath = "//button[contains(text(), 'Select account')]"
            self.move_and_click(xpath, 180, True, "click continue at account selection screen", self.step, "clickable")
            self.increase_step()

            xpath = "//h4[text()='Storage']"
            self.move_and_click(xpath, 30, True, "click the 'storage' link", self.step, "clickable")
            
            self.set_cookies()

        except TimeoutException:
            self.output(f"Step {self.step} - Failed to find or switch to the iframe within the timeout period.", 1)

        except Exception as e:
            self.output(f"Step {self.step} - An error occurred: {e}", 1)

    def full_claim(self):
        self.step = "100"

        def apply_random_offset(unmodifiedTimer):
            if self.settings['lowestClaimOffset'] <= self.settings['highestClaimOffset']:
                self.random_offset = random.randint(self.settings['lowestClaimOffset'], self.settings['highestClaimOffset'])
                modifiedTimer = unmodifiedTimer + self.random_offset
                self.output(f"Step {self.step} - Random offset applied to the wait timer of: {self.random_offset} minutes.", 2)
                return modifiedTimer

        self.launch_iframe()

        xpath = "//h4[text()='Storage']"
        self.move_and_click(xpath, 20, True, "click the 'storage' link", self.step, "clickable")

        self.increase_step()

        self.get_balance(False)

        wait_time_text = self.get_wait_time(self.step, "pre-claim") 

        if wait_time_text != "Filled":
            matches = re.findall(r'(\d+)([hm])', wait_time_text)
            remaining_wait_time = (sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches)) + self.random_offset
            if remaining_wait_time < 5 or self.settings["forceClaim"]:
                self.settings['forceClaim'] = True
                self.output(f"Step {self.step} - the remaining time to claim is less than the random offset, so applying: settings['forceClaim'] = True", 3)
            else:
                self.output(f"STATUS: Considering {wait_time_text}, we'll go back to sleep for {remaining_wait_time} minutes.", 1)
                return remaining_wait_time

        if wait_time_text == "Unknown":
            return 15

        try:
            self.output(f"Step {self.step} - The pre-claim wait time is : {wait_time_text} and random offset is {self.random_offset} minutes.", 1)
            self.increase_step()

            if wait_time_text == "Filled" or self.settings['forceClaim']:
                try:
                    original_window = self.driver.current_window_handle
                    xpath = "//button[contains(text(), 'Check NEWS')]"
                    self.move_and_click(xpath, 3, True, "check for NEWS.", self.step, "clickable")
                    self.driver.switch_to.window(original_window)
                except TimeoutException:
                    if self.settings['debugIsOn']:
                        self.output(f"Step {self.step} - No news to check or button not found.", 3)
                self.increase_step()

                try:
                    self.select_iframe(self.step)
                    self.increase_step()
                    
                    xpath = "//button[contains(text(), 'Claim HOT')]"
                    self.move_and_click(xpath, 30, True, "click the claim button", self.step, "clickable")
                    self.increase_step()

                    self.output(f"Step {self.step} - Let's wait for the pending Claim spinner to stop spinning...", 2)
                    time.sleep(5)
                    wait = WebDriverWait(self.driver, 240)
                    spinner_xpath = "//*[contains(@class, 'spinner')]" 
                    try:
                        wait.until(EC.invisibility_of_element_located((By.XPATH, spinner_xpath)))
                        self.output(f"Step {self.step} - Pending action spinner has stopped.\n", 3)
                    except TimeoutException:
                        self.output(f"Step {self.step} - Looks like the site has lag - the Spinner did not disappear in time.\n", 2)
                    self.increase_step()
                    wait_time_text = self.get_wait_time(self.step, "post-claim") 
                    matches = re.findall(r'(\d+)([hm])', wait_time_text)
                    total_wait_time = apply_random_offset(sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches))
                    self.increase_step()

                    self.get_balance(True)

                    if wait_time_text == "Filled":
                        self.output(f"STATUS: The wait timer is still showing: Filled.", 1)
                        self.output(f"Step {self.step} - This means either the claim failed, or there is >4 minutes lag in the game.", 1)
                        self.output(f"Step {self.step} - We'll check back in 1 hour to see if the claim processed and if not try again.", 2)
                    else:
                        self.output(f"STATUS: Successful Claim: Next claim {wait_time_text} / {total_wait_time} minutes.", 1)
                    return max(60, total_wait_time)

                except TimeoutException:
                    self.output(f"STATUS: The claim process timed out: Maybe the site has lag? Will retry after one hour.", 1)
                    return 60
                except Exception as e:
                    self.output(f"STATUS: An error occurred while trying to claim: {e}\nLet's wait an hour and try again", 1)
                    return 60

            else:
                matches = re.findall(r'(\d+)([hm])', wait_time_text)
                if matches:
                    total_time = sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches)
                    total_time += 1
                    total_time = max(5, total_time)
                    self.output(f"Step {self.step} - Not Time to claim this wallet yet. Wait for {total_time} minutes until the storage is filled.", 2)
                    return total_time
                else:
                    self.output(f"Step {self.step} - No wait time data found? Let's check again in one hour.", 2)
                    return 60
        except Exception as e:
            self.output(f"Step {self.step} - An unexpected error occurred: {e}", 1)
            return 60

    def get_balance(self, claimed=False):
        prefix = "After" if claimed else "Before"
        default_priority = 2 if claimed else 3

        priority = max(self.settings['verboseLevel'], default_priority)
        balance_text = f'{prefix} BALANCE:' if claimed else f'{prefix} BALANCE:'
        balance_xpath = f"//p[contains(text(), 'HOT')]/following-sibling::img/following-sibling::p"

        try:
            element = self.monitor_element(balance_xpath)
            if element:
                balance_part = element # .text.strip()
                self.output(f"Step {self.step} - {balance_text} {balance_part}", priority)

        except NoSuchElementException:
            self.output(f"Step {self.step} - Element containing '{prefix} Balance:' was not found.", priority)
        except Exception as e:
            self.output(f"Step {self.step} - An error occurred: {str(e)}", priority)
        
        self.increase_step()

    def get_wait_time(self, step_number="108", beforeAfter="pre-claim", max_attempts=2):
        for attempt in range(1, max_attempts + 1):
            try:
                xpath = f"//div[contains(., 'Storage')]//p[contains(., '{self.pot_full}') or contains(., '{self.pot_filling}')]"
                wait_time_element = self.move_and_click(xpath, 20, True, f"get the {beforeAfter} wait timer", self.step, "visible")
                if wait_time_element is not None:
                    return wait_time_element.text
                else:
                    self.output(f"Step {self.step} - Attempt {attempt}: Wait time element not found. Clicking the 'Storage' link and retrying...", 3)
                    storage_xpath = "//h4[text()='Storage']"
                    self.move_and_click(storage_xpath, 30, True, "click the 'storage' link", f"{self.step} recheck", "clickable")
                    self.output(f"Step {self.step} - Attempted to select storage again...", 3)
                return wait_time_element.text

            except TimeoutException:
                if attempt < max_attempts:
                    self.output(f"Step {self.step} - Attempt {attempt}: Wait time element not found. Clicking the 'Storage' link and retrying...", 3)
                    storage_xpath = "//h4[text()='Storage']"
                    self.move_and_click(storage_xpath, 30, True, "click the 'storage' link", f"{self.step} recheck", "clickable")
                else:
                    self.output(f"Step {self.step} - Attempt {attempt}: Wait time element not found.", 3)

            except Exception as e:
                self.output(f"Step {self.step} - An error occurred on attempt {attempt}: {e}", 3)

        return "Unknown"

def main():
    claimer = HotClaimer()
    claimer.run()

if __name__ == "__main__":
    main()
