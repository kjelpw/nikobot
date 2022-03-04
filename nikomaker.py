import discord
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import FirefoxOptions
async def niko_browser(ctx, niko_message):
    #navigate to page
    opts = FirefoxOptions()
    opts.add_argument('--headless')
    driver = webdriver.Firefox(options=opts)
    driver.get('https://gh.princessrtfm.com/niko.html')
    assert 'NikoMaker' in driver.title

    #find and click normal face
    face = driver.find_element_by_css_selector('.normal')
    face.click()

    #find and use the textbox
    textbox = driver.find_element_by_id('message')
    textbox.clear()
    if niko_message == None:
        niko_message = ''
    textbox.send_keys(niko_message)

    #download the image
    with open('nikomessage.png', 'wb') as file:
        file.write(driver.find_element_by_id('render').screenshot_as_png)

    #send the image
    await ctx.channel.send(file=discord.File('nikomessage.png'))
    driver.close()