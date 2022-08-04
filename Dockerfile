FROM python:3.9.5-alpine3.13

RUN apk update && apk upgrade && apk add ca-certificates ffmpeg opus brotli

RUN apk add --virtual build-essentials build-base alpine-sdk libffi-dev

RUN mkdir /app/
ADD . /app/
WORKDIR /app

RUN pip install pipenv
RUN pipenv install --system --deploy

RUN apk del build-essentials

RUN apk add git

ENTRYPOINT [ "python", "./src/main.py" ]
CMD []
