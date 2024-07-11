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

class FuelClaimer(Claimer):

    def __init__(self):
        self.settings_file = "variables.txt"
        self.status_file_path = "status.txt"
        self.load_settings()
        self.random_offset = random.randint(max(self.settings['lowestClaimOffset'], 0), max(self.settings['highestClaimOffset'], 0))
        self.script = "games/fuel.py"
        self.prefix = "Fuel:"
        self.url = "https://web.telegram.org/k/#@fueljetton_bot"
        self.pot_full = "Filled"
        self.pot_filling = "to fill"
        self.seed_phrase = None
        self.forceLocalProxy = False
        self.forceRequestUserAgent = True

        super().__init__()

        self.start_app_xpath = "//span[contains(text(), 'Start pumping oil')]"

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
            self.output(f"Step {self.step} - Failed to find or switch to the iframe within the timeout period.", 1)

        except Exception as e:
            self.output(f"Step {self.step} - An error occurred: {e}", 1)

    def full_claim(self):
        self.step = "100"

        def recycle():
            try:
                xpath = "//a[text()='Recycling']"
                success = self.move_and_click(xpath, 10, True, "click the 'Recycling' button", self.step, "clickable")
                if success:
                    self.output(f"Step {self.step} - successful: Clicked on the 'Recycling' link", 2)
                    self.increase_step()
                    time.sleep(20)
                else:
                    self.output(f"Step {self.step} - failed: Unable to click on the 'Recycling' link", 2)
                    return
                
                xpath = "//button[@class='recycle-button']"
                self.move_and_click(xpath, 10, True, "Refining Oil to FuelWith good PH :) AHAH brumb", self.step, "clickable")
                self.increase_step()
                
            except Exception as e:
                self.output(f"An error occurred: {str(e)}")

        def adverts():
            xpath = "//a[text()='Upgrades']"
            self.move_and_click(xpath, 10, True, "click the 'Upgrades' button", self.step, "clickable")
            xpath = "//button[contains(., 'Increase multiplier by')]"
            advert = self.move_and_click(xpath, 10, True, "watch an advert", self.step, "clickable")
            if advert:
                self.output(f"Step {self.step} - Waiting 60 seconds for the advert to play.", 3)
                time.sleep(60)
                self.increase_step()

        def apply_random_offset(unmodifiedTimer):
            if self.settings['lowestClaimOffset'] <= self.settings['highestClaimOffset']:
                self.random_offset = random.randint(self.settings['lowestClaimOffset'], self.settings['highestClaimOffset'])
                modifiedTimer = unmodifiedTimer + self.random_offset
                self.output(f"Step {self.step} - Random offset applied to the wait timer of: {self.random_offset} minutes.", 2)
                return modifiedTimer

        self.launch_iframe()

        self.get_balance(False)
        wait_time_text = self.get_wait_time(self.step, "pre-claim") 

        if wait_time_text != "Filled":
            try:
                time_parts = wait_time_text.split()
                hours = int(time_parts[0].strip('h'))
                minutes = int(time_parts[1].strip('m'))
                remaining_wait_time = (hours * 60 + minutes)
                if remaining_wait_time < 5 or self.settings["forceClaim"]:
                    self.settings['forceClaim'] = True
                    self.output(f"Step {self.step} - the remaining time to claim is less than the random offset, so applying: settings['forceClaim'] = True", 3)
                else:
                    remaining_wait_time = 30
                    adverts()
                    self.output(f"STATUS: Pot not ready for claiming - let's come back in 30 minutes to check for adverts.", 1)
                    return remaining_wait_time
            except ValueError:
                pass

        if wait_time_text == "Unknown":
            return 15

        try:
            self.output(f"Step {self.step} - The pre-claim wait time is : {wait_time_text} and random offset is {self.random_offset} minutes.", 1)
            self.increase_step()

            if wait_time_text == "Filled" or self.settings['forceClaim']:
                
                try:
                    xpath = "//button[contains(text(), 'Send to warehouse')]"
                    self.move_and_click(xpath, 10, True, "click the 'Launch' button", self.step, "clickable")

                    self.output(f"Step {self.step} - Waiting 10 seconds for the totals and timer to update...", 3) 
                    time.sleep(10)
                    
                    wait_time_text = self.get_wait_time(self.step, "post-claim") 
                    matches = re.findall(r'(\d+)([hm])', wait_time_text)
                    total_wait_time = apply_random_offset(sum(int(value) * (60 if unit == 'h' else 1) for value, unit in matches))
                    self.increase_step()
                    self.get_balance(True)
                    self.increase_step()
                    recycle()
                    if wait_time_text == "Filled":
                        self.output(f"Step {self.step} - The wait timer is still showing: Filled.", 1)
                        self.output(f"Step {self.step} - This means either the claim failed, or there is >4 minutes lag in the game.", 1)
                        self.output(f"Step {self.step} - We'll check back in 1 hour to see if the claim processed and if not try again.", 2)
                    else:
                        self.output(f"STATUS: Pot full in {total_wait_time} minutes. We'll come back in 30 to check for adverts.", 1)
                    return 30

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
        balance_xpath = f"//span[@class='fuel-balance']"
        balance_part = None

        try:
            self.move_and_click(balance_xpath, 30, False, "look for fuel balance", self.step, "visible")
            fuel = self.monitor_element(balance_xpath)
            balance_xpath = f"//span[@class='fuel-balance']/preceding-sibling::span[1]"
            self.move_and_click(balance_xpath, 30, False, "look for oil balance", self.step, "visible")
            oil = self.monitor_element(balance_xpath)
            balance_part = f"{fuel} fuel & {oil} oil."
            self.output(f"Step {self.step} - {balance_text} {balance_part}", priority)

        except NoSuchElementException:
            self.output(f"Step {self.step} - Element containing '{prefix} Balance:' was not found.", priority)
        except Exception as e:
            self.output(f"Step {self.step} - An error occurred: {str(e)}", priority) 

        self.increase_step()

    def get_wait_time(self, step_number="108", beforeAfter="pre-claim", max_attempts=1):
        for attempt in range(1, max_attempts + 1):
            try:
                self.output(f"Step {self.step} - check if the timer is elapsing...", 3)
                xpath = "//div[@class='in-storage-footer']"
                pot_full_value = self.monitor_element(xpath, 15)
                return pot_full_value
            except Exception as e:
                self.output(f"Step {self.step} - An error occurred on attempt {attempt}: {e}", 3)
                return "Unknown"

        return "Unknown"

def main():
    claimer = FuelClaimer()
    claimer.run()

if __name__ == "__main__":
    main()