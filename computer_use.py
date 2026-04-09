"""
computer_use.py
───────────────
Controls your browser to interact with websites.
Uses Selenium — a real browser automation tool.

WHAT THIS CAN DO:
  - Open Binance website in Chrome
  - Navigate to a trading pair
  - Take screenshots of charts
  - Fill in trade forms and click buttons

HONEST LIMITS:
  - Binance has security that detects automation
  - They may require 2FA which blocks bots
  - API trading (binance_trader.py) is more reliable
  - Use this only for screenshots/monitoring
    unless you fully understand Binance's terms

INSTALL:
  pip install selenium webdriver-manager
"""

import time


class ComputerUse:

    def __init__(self, config):
        self.config  = config
        self.enabled = config.get("use_browser", False)
        self.driver  = None

        if self.enabled:
            self._init_browser()
        else:
            print("    [Browser] Disabled — set use_browser=True to enable")

    def _init_browser(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager

            options = Options()
            # Remove headless to see the browser window
            # options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1280,800")

            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )
            print("    [Browser] Chrome browser ready")

        except ImportError:
            print("    [Browser] selenium not installed — run: pip install selenium webdriver-manager")
            self.enabled = False
        except Exception as e:
            print(f"    [Browser] Could not start browser: {e}")
            self.enabled = False

    # ──────────────────────────────────────────────
    # TAKE SCREENSHOT OF BINANCE CHART
    # ──────────────────────────────────────────────

    def screenshot_chart(self, symbol):
        if not self.enabled or not self.driver:
            return None
        try:
            coin = symbol.replace("/","")
            url  = f"https://www.binance.com/en/futures/{coin}"
            self.driver.get(url)
            time.sleep(4)   # wait for chart to load
            path = f"chart_{coin}_{int(time.time())}.png"
            self.driver.save_screenshot(path)
            print(f"    [Browser] Chart screenshot saved: {path}")
            return path
        except Exception as e:
            print(f"    [Browser] Screenshot failed: {e}")
            return None

    # ──────────────────────────────────────────────
    # PLACE TRADE VIA BROWSER
    # NOTE: Binance API is more reliable for this.
    # Only use browser trading if API is not available.
    # ──────────────────────────────────────────────

    def place_trade_on_binance(self, symbol, direction, levels):
        """
        IMPORTANT: Binance has anti-bot detection.
        This may not work reliably due to Binance security.
        Using the API via binance_trader.py is better.
        This is here for educational purposes only.
        """
        if not self.enabled or not self.driver:
            print("    [Browser] Browser not available — use API trading instead")
            return

        print(f"    [Browser] NOTE: API trading is more reliable than browser trading")
        print(f"    [Browser] Switch to binance_trader.py for real orders")

    # ──────────────────────────────────────────────
    # OPEN ANY URL AND READ PAGE TEXT
    # ──────────────────────────────────────────────

    def read_page(self, url):
        if not self.enabled or not self.driver:
            return None
        try:
            self.driver.get(url)
            time.sleep(3)
            return self.driver.find_element("tag name", "body").text
        except Exception as e:
            print(f"    [Browser] Read page error: {e}")
            return None

    def close(self):
        if self.driver:
            self.driver.quit()
            print("    [Browser] Browser closed")
