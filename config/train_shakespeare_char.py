# train a miniature character-level shakespeare model
# good for debugging and playing on macbooks and such

out_dir = "out-shakespeare-char"
eval_interval = 250  # keep frequent because we'll overfit
eval_iters = 200
log_interval = 10  # don't print too too often

# we expect to overfit on this small dataset, so only save when val improves
always_save_checkpoint = False

wandb_log = False  # override via command line if you like
wandb_project = "shakespeare-char"
wandb_run_name = "mini-gpt"

dataset = "shakespeare_char"
batch_size = 32
block_size = 256  # context of up to 256 previous characters

# baby GPT model :)
n_layer = 16
n_head = 16
n_embd = 1024  #  // 2  # 768 // 2
dropout = 0.0

learning_rate = 4e-6  # with baby networks can afford to go a bit higher
max_iters = 20
lr_decay_iters = 5000  # make equal to max_iters usually
min_lr = 1e-4  # learning_rate / 10 usually
beta2 = 0.99  # make a bit bigger because number of tokens per iter is small

warmup_iters = 2  # not super necessary potentially

# on macbook also add
# device = 'cpu'  # run on cpu only
# compile = False # do not torch compile the model
