"""Meme generation using imgflip API"""
import requests
import config


class MemeGenerator:
    """Generate memes using imgflip API"""
    
    CAPTION_URL = 'https://api.imgflip.com/caption_image'
    TEMPLATE_ID_STUFF = '367801389'
    TEMPLATE_ID_AIDNA = '369320225'
    
    def __init__(self):
        self.username = config.IMGFLIP_USERNAME
        self.password = config.IMGFLIP_PASSWORD
        
    def _create_meme(self, template_id: str, text: str) -> str:
        """
        Create a meme with the given template and text
        
        Args:
            template_id: The imgflip template ID
            text: Text to add to the meme
            
        Returns:
            URL of the generated meme or error message
        """
        try:
            payload = {
                'template_id': template_id,
                'username': self.username,
                'password': self.password,
                'text0': text,
                'text1': ''
            }
            
            response = requests.post(self.CAPTION_URL, payload, timeout=30).json()
            
            if response.get('success'):
                return response['data']['url']
            else:
                return response.get('error_message', 'Unknown error')
                
        except requests.RequestException as e:
            return f'Request failed: {str(e)}'
        except Exception as e:
            return f'Error: {str(e)}'
            
    def make_meme_stuff(self, text: str) -> str:
        """
        Create a 'stuff' (Tony Stark) meme
        
        Args:
            text: Text for the meme
            
        Returns:
            URL of the generated meme or error message
        """
        return self._create_meme(self.TEMPLATE_ID_STUFF, text)
        
    def make_meme_aidna(self, text: str) -> str:
        """
        Create an 'aidna' meme
        
        Args:
            text: Text for the meme
            
        Returns:
            URL of the generated meme or error message
        """
        return self._create_meme(self.TEMPLATE_ID_AIDNA, text)
