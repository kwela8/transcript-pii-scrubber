# Source before a run: four threads, no network for models, caches in the working folder.
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
export HF_HOME="${BENCH_DIR:-$PWD}/hf-cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
