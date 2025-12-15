"""NikoMaker image generator using Selenium"""
import asyncio
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class NikoGenerator:
    """Generate NikoQuote images using Selenium"""
    
    NIKO_URL = 'https://gh.princessrtfm.com/niko.html'
    OUTPUT_FILE = 'nikomessage.png'
    
    def __init__(self):
        self.options = Options()
        self.options.add_argument('--headless')
        
    async def create_niko_image(self, message: str) -> str:
        """
        Create a NikoQuote image with the given message
        
        Args:
            message: Text to put in the NikoQuote
            
        Returns:
            Path to the generated image file
        """
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._generate_image, message)
        
    def _generate_image(self, message: str) -> str:
        """
        Generate the NikoQuote image (blocking operation)
        
        Args:
            message: Text to put in the NikoQuote
            
        Returns:
            Path to the generated image file
        """
        driver = None
        try:
            # Initialize Firefox driver
            driver = webdriver.Firefox(options=self.options)
            driver.get(self.NIKO_URL)
            
            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.normal'))
            )
            
            # Find and click normal face
            face = driver.find_element(By.CSS_SELECTOR, '.normal')
            face.click()
            
            # Find and use the textbox
            textbox = driver.find_element(By.ID, 'message')
            textbox.clear()
            
            if message:
                textbox.send_keys(message)
            
            # Wait a moment for rendering
            time.sleep(1)
            
            # Take screenshot of the render element
            render_element = driver.find_element(By.ID, 'render')
            screenshot_data = render_element.screenshot_as_png
            
            # Save the image
            with open(self.OUTPUT_FILE, 'wb') as file:
                file.write(screenshot_data)
                
            return self.OUTPUT_FILE
            
        finally:
            if driver:
                driver.quit()
