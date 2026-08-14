# interactor-voxhammer-image-mesh-editing -- vast.ai worker, RFD 0036/0048.
#
# No weights of its own -- runs on microsoft/TRELLIS.2's backbone (RFD 0038).
# Builds FROM weftspun/trellis2-base's worker stage, same reasoning as
# interactor-voxhammer-text-mesh-editing (RFD 0048 shares RFD 0047's domain).

FROM python:3.11-slim AS contract
WORKDIR /app
RUN pip install --no-cache-dir usd-core==25.5 fastapi==0.115.5 uvicorn==0.32.1 pydantic==2.10.3
COPY server.py /app/server.py
COPY domain.ex problem.ex plan.ex /app/
COPY test_input.json /app/test_input.json
ENV WEFTSPUN_STUB=1 PORT=8000
EXPOSE 8000
CMD ["python", "/app/server.py"]

FROM weftspun/trellis2-base AS worker

WORKDIR /app
COPY server.py /app/server.py
COPY domain.ex problem.ex plan.ex /app/

# VoxHammer itself -- MIT, its code that wraps TRELLIS.2's latents for
# editing. Not yet wired into server.py's _run_plan (see README's Status).
ARG VOXHAMMER_REF=main
RUN git clone https://github.com/Nelipot-Lee/VoxHammer.git /src/VoxHammer \
    && git -C /src/VoxHammer checkout "${VOXHAMMER_REF}"

ENV PORT=8000
EXPOSE 8000

CMD ["python3", "-u", "/app/server.py"]
