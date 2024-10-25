FROM ubuntu:22.04

ARG UID=10001
RUN apt-get update && apt-get install -y python3 python3-pip jq && apt-get upgrade -y && apt-get autoremove -y
RUN mkdir -p /user/appuser && mkdir -p /app && mkdir -p /app/deleted && mkdir -p /app/added && mkdir -p /app/modified

RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/user/appuser" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

ADD ./watchanyresource.py /app/watchanyresource.py
ADD ./requirements.txt /app/requirements.txt
RUN pip3 install -r /app/requirements.txt

USER appuser

CMD ["python3","/app/watchanyresource.py"]
