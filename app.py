from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def hello_world():
    return '<p>Hello, World!</p>'

@app.route('/log')
def log():
    fname = 'log.txt'
    N = 4
    bufsize = 8192
    # calculating size of
    # file in bytes
    fsize = os.stat(fname).st_size

    iter = 0
     
    # opening file using with() method
    # so that file get closed
    # after completing work
    with open(fname) as f:
        if bufsize > fsize:
            
            # adjusting buffer size
            # according to size
            # of file
            bufsize = fsize-1
            
            # list to store
            # last N lines
            fetched_lines = []
            
            # while loop to
            # fetch last N lines
            while True:
                iter += 1
                
                # moving cursor to
                # the last Nth line
                # of file
                f.seek(fsize-bufsize * iter)
                
                # storing each line
                # in list upto
                # end of file
                lines = f.read
                for line in f.readlines():
                    fetched_lines.append('<p>' + str(line) + '</p>')
                
                # halting the program
                # when size of list
                # is equal or greater to
                # the number of lines requested or
                # when we reach end of file
                if len(fetched_lines) >= N or f.tell() == 0:
                    return ''.join(fetched_lines[-N:])

if __name__ == '__main__' :
    app.run(host='0.0.0.0')