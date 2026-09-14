# Evaluation Using Gemini
api_key=xxx
model_marker=xxx
api_url=xxx
screenshots_count=3
path_with_index=xxx
save_path=xxx
screenshots_dir=xxx
tokenizer_dir=xxx
num_processes=16
python3 src/infer_gemini.py \
    $path_with_index \
    $save_path \
    $screenshots_dir \
    $screenshots_count \
    $api_key \
    $model_marker \
    $api_url \
    $tokenizer_dir \
    --num_processes $num_processes

# # Evaluation Using Qwen2.5-VL-72B-Instruct
# MODEL_DIR="/xxx/Qwen2.5-VL-72B-Instruct"
# HOST_IP=$(hostname -i)
# model_name=$(basename $MODEL_DIR)
# nohup python3 -m vllm.entrypoints.openai.api_server \
#     --enforce-eager --swap-space 50 --disable-log-requests \
#     --dtype float16 --trust-remote-code \
#     --model ${MODEL_DIR} --served-model-name ${model_name} \
#     --gpu-memory-utilization 0.9 --port 8088 \
#     --max-model-len 32768 --max-seq-len 32768 \
#     --limit-mm-per-prompt "image=5"\
#     --tensor-parallel-size 8 \
#     --seed 1024 > /root/log.ds_server 2> /root/err.ds_server &
# sleep 10m

# screenshots_count=3
# path_with_index=xxx
# save_path=xxx
# screenshots_dir=xxx
# tokenizer_dir=$MODEL_DIR
# ip_file_path=$HOST_IP # ip or ip_list_file
# num_processes=16
# python3 src/infer_qvl.py \
#   $path_with_index \
#   $save_path \
#   $screenshots_dir \
#   $screenshots_count \
#   $model_name \
#   $tokenizer_dir \
#   $ip_file_path \
#   --num_processes $num_processes