import glob
import os
import time

import gradio as gr
import modules.generation_parameters_copypaste as parameters_copypaste
import requests
from modules import script_callbacks, shared
from modules.ui_components import ToolButton as ToolButton_webui
from scripts.easyphoto_config import (DEFAULT_SCENE_LORA, cache_log_file_path,
                                      easyphoto_outpath_samples,
                                      easyphoto_video_outpath_samples,
                                      models_path, user_id_outpath_samples)
from scripts.easyphoto_infer import (easyphoto_infer_forward,
                                     easyphoto_video_infer_forward)
from scripts.easyphoto_train import easyphoto_train_forward
from scripts.easyphoto_utils import check_id_valid, check_scene_valid, check_files_exists_and_download
from scripts.sdwebui import get_checkpoint_type, get_scene_prompt

gradio_compat = True

try:
    from distutils.version import LooseVersion

    from importlib_metadata import version
    if LooseVersion(version("gradio")) < LooseVersion("3.10"):
        gradio_compat = False
except ImportError:
    pass

def get_external_ckpts():
    external_checkpoints = []
    external_ckpt_dir = shared.cmd_opts.ckpt_dir if shared.cmd_opts.ckpt_dir else []
    if len(external_ckpt_dir) > 0:
        for _checkpoint in os.listdir(external_ckpt_dir):
            if _checkpoint.endswith(("pth", "safetensors", "ckpt")):
                external_checkpoints.append(_checkpoint)
    return external_checkpoints
external_checkpoints = get_external_ckpts()

def checkpoint_refresh_function():
    checkpoints = []
    models_dir = os.path.join(models_path, "Stable-diffusion")
    
    for root, dirs, files in os.walk(models_dir):
        for _checkpoint in files:
            if _checkpoint.endswith(("pth", "safetensors", "ckpt")):
                rel_path = os.path.relpath(os.path.join(root, _checkpoint), models_dir)
                checkpoints.append(rel_path)
    
    return gr.update(choices=list(set(["Chilloutmix-Ni-pruned-fp16-fix.safetensors"] + checkpoints + external_checkpoints)))
    
checkpoints = []
models_dir = os.path.join(models_path, "Stable-diffusion")

for root, dirs, files in os.walk(models_dir):
    for _checkpoint in files:
        if _checkpoint.endswith(("pth", "safetensors", "ckpt")):
            rel_path = os.path.relpath(os.path.join(root, _checkpoint), models_dir)
            checkpoints.append(rel_path)

def upload_file(files, current_files):
    file_paths = [file_d['name'] for file_d in current_files] + [file.name for file in files]
    return file_paths

def refresh_display():
    if not os.path.exists(os.path.dirname(cache_log_file_path)):
        os.makedirs(os.path.dirname(cache_log_file_path), exist_ok=True)
    lines_limit = 3
    try:
        with open(cache_log_file_path, "r", newline="") as f:
            lines = []
            for s in f.readlines():
                line = s.replace("\x00", "")
                if line.strip() == "" or line.strip() == "\r":
                    continue
                lines.append(line)

            total_lines = len(lines)
            if total_lines <= lines_limit:
                chatbot = [(None, ''.join(lines))]
            else:
                chatbot = [(None, ''.join(lines[total_lines-lines_limit:]))]
            return chatbot
    except Exception:
        with open(cache_log_file_path, "w") as f:
            pass
        return None

class ToolButton(gr.Button, gr.components.FormComponent):
    """Small button with single emoji as text, fits inside gradio forms"""

    def __init__(self, **kwargs):
        super().__init__(variant="tool", 
                         elem_classes=kwargs.pop('elem_classes', []) + ["cnet-toolbutton"], 
                         **kwargs)

    def get_block_name(self):
        return "button"

def on_ui_tabs():
    with gr.Blocks(analytics_enabled=False) as easyphoto_tabs:
        with gr.TabItem('Train'):
            dummy_component = gr.Label(visible=False)
            with gr.Blocks():
                with gr.Row():
                    uuid = gr.Text(label="User_ID", value="", visible=False)

                    with gr.Column():
                        gr.Markdown('Training photos')

                        instance_images = gr.Gallery().style(columns=[4], rows=[2], object_fit="contain", height="auto")

                        with gr.Row():
                            upload_button = gr.UploadButton(
                                "Upload Photos", file_types=["image"], file_count="multiple"
                            )
                            clear_button = gr.Button("Clear Photos")
                        clear_button.click(fn=lambda: [], inputs=None, outputs=instance_images)

                        upload_button.upload(upload_file, inputs=[upload_button, instance_images], outputs=instance_images, queue=False)

                        human_upload_note = gr.Markdown(
                            '''
                            Training steps:
                            1. Please upload 5-20 half-body photos or head-and-shoulder photos, and please don't make the proportion of your face too small.
                            2. Click on the Start Training button below to start the training process, approximately 25 minutes.
                            3. Switch to Inference and generate photos based on the template. 
                            4. If you encounter lag when uploading, please modify the size of the uploaded pictures and try to limit it to 1.5MB.
                            '''
                        )
                        scene_upload_note = gr.Markdown(
                            '''
                            Training steps:
                            1. Please upload 15-20 photos with human, and please don't make the proportion of your face too small.
                            2. Click on the Start Training button below to start the training process, approximately 25 minutes.
                            3. Switch to Inference and generate photos based on the scene lora. 
                            4. If you encounter lag when uploading, please modify the size of the uploaded pictures and try to limit it to 1.5MB.
                            '''
                        )
                    with gr.Column():
                        gr.Markdown('Params Setting')
                        with gr.Accordion("Advanced Options", open=True):
                            with gr.Row():
                                train_mode_choose = gr.Dropdown(value="Train Human Lora", elem_id='radio', scale=1, min_width=20, choices=["Train Human Lora", "Train Scene Lora"], label="The Type of Lora", visible=True)

                                sd_model_checkpoint = gr.Dropdown(value="Chilloutmix-Ni-pruned-fp16-fix.safetensors", scale=3, choices=list(set(["Chilloutmix-Ni-pruned-fp16-fix.safetensors"] + checkpoints + external_checkpoints)), label="The base checkpoint you use.", visible=True)

                                checkpoint_refresh = ToolButton(value="\U0001f504")
                                checkpoint_refresh.click(
                                    fn=checkpoint_refresh_function,
                                    inputs=[],
                                    outputs=[sd_model_checkpoint]
                                )

                            with gr.Row(visible=False) as sdxl_row:
                                sdxl_wiki_url = "https://github.com/aigc-apps/sd-webui-EasyPhoto/wiki#4sdxl-training"
                                sdxl_training_note = gr.Markdown(
                                    value = "**Please check the [[wiki]]({}) before SDXL training**.".format(sdxl_wiki_url),
                                    visible=True
                                )
                                
                            with gr.Row(visible=False) as training_prefix_prompt_row:
                                training_prefix_prompt = gr.Textbox(
                                    label="Corresponding Prompts to the Template. (Such as: 1girl, brown_hair, chinese_clothes, dress, earrings, floral_print, hair_ornament, jewelry, lips, makeup, necklace, beige)", 
                                    placeholder="Please write the corresponding prompts to the template.", 
                                    lines=1, value='', visible=True, interactive=True
                                )

                            with gr.Row():
                                crop_ratio = gr.Textbox(
                                    label="crop ratio",
                                    value=3,
                                    interactive=True,
                                    visible=False
                                )
                                resolution = gr.Textbox(
                                    label="resolution",
                                    value=512,
                                    interactive=True
                                )
                                val_and_checkpointing_steps = gr.Textbox(
                                    label="validation & save steps",
                                    value=100,
                                    interactive=True
                                )
                                max_train_steps = gr.Textbox(
                                    label="max train steps",
                                    value=800,
                                    interactive=True
                                )
                                steps_per_photos = gr.Textbox(
                                    label="max steps per photos",
                                    value=200,
                                    interactive=True
                                )
                            with gr.Row():
                                train_batch_size = gr.Textbox(
                                    label="train batch size",
                                    value=1,
                                    interactive=True
                                )
                                gradient_accumulation_steps = gr.Textbox(
                                    label="gradient accumulation steps",
                                    value=4,
                                    interactive=True
                                )
                                dataloader_num_workers =  gr.Textbox(
                                    label="dataloader num workers",
                                    value=16,
                                    interactive=True
                                )
                                learning_rate = gr.Textbox(
                                    label="learning rate",
                                    value=1e-4,
                                    interactive=True
                                )
                            with gr.Row():
                                rank = gr.Textbox(
                                    label="rank",
                                    value=128,
                                    interactive=True
                                )
                                network_alpha = gr.Textbox(
                                    label="network alpha",
                                    value=64,
                                    interactive=True
                                )
                            with gr.Row():
                                validation = gr.Checkbox(
                                    label="Validation",  
                                    value=True
                                )
                                enable_rl = gr.Checkbox(
                                    label="Enable RL (Reinforcement Learning)",
                                    value=False
                                )
                                skin_retouching_bool = gr.Checkbox(
                                    label="Skin Retouching",
                                    value=True
                                )
                            
                            # Reinforcement Learning Options
                            with gr.Row(visible=False) as rl_option_row1:
                                max_rl_time = gr.Slider(
                                    minimum=1, maximum=12, value=1,
                                    step=0.5, label="max time (hours) of RL"
                                )
                                timestep_fraction = gr.Slider(
                                    minimum=0.7, maximum=1, value=1,
                                    step=0.05, label="timestep fraction"
                                )
                            rl_notes = gr.Markdown(
                                value = '''
                                RL notes:
                                - The RL is an experimental feature aiming to improve the face similarity score of generated photos w.r.t uploaded photos.
                                - Setting (**max rl time** / **timestep fraction**) > 2 is recommended for a stable training result.
                                - 16GB GPU memory is required at least.
                                ''',
                                visible=False
                            )
                            enable_rl.change(lambda x: rl_option_row1.update(visible=x), inputs=[enable_rl], outputs=[rl_option_row1])
                            enable_rl.change(lambda x: rl_option_row1.update(visible=x), inputs=[enable_rl], outputs=[rl_notes])

                            # We will update the default training parameters by the checkpoint type. 
                            def update_train_parameters(sd_model_checkpoint):
                                checkpoint_type = get_checkpoint_type(sd_model_checkpoint)
                                if checkpoint_type == 3:  # SDXL
                                    return gr.Markdown.update(visible=True), 1024, 600, 32, 16, gr.Checkbox.update(value=False)
                                return gr.Markdown.update(visible=False), 512, 800, 128, 64, gr.Checkbox.update(value=True)
                            
                            sd_model_checkpoint.change(
                                fn=update_train_parameters,
                                inputs=sd_model_checkpoint,
                                outputs=[sdxl_row, resolution, max_train_steps, rank, network_alpha, validation]
                            )

                        human_train_notes = gr.Markdown(
                            '''
                            Parameter parsing:
                            - **max steps per photo** represents the maximum number of training steps per photo.
                            - **max train steps** represents the maximum training step.
                            - **Validation** Whether to validate at training time.
                            - **Final training step** = Min(photo_num * max_steps_per_photos, max_train_steps).
                            - **Skin retouching** Whether to use skin retouching to preprocess training data face
                            '''
                        )
                        scene_train_notes = gr.Markdown(
                            '''
                            Parameter parsing:
                            - **max steps per photo** represents the maximum number of training steps per photo.
                            - **max train steps** represents the maximum training step.
                            - **Final training step** = Min(photo_num * max_steps_per_photos, max_train_steps).
                            ''',
                            visible=False
                        )

                        def update_train_mode(train_mode_choose):
                            if train_mode_choose == "Train Human Lora":
                                return [gr.update(value=512), gr.update(value=128), gr.update(value=64), gr.update(visible=False), gr.update(visible=False), gr.update(visible=True), gr.update(visible=True), gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), gr.update(visible=True), gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), gr.update(visible=True)]
                            else:
                                return [gr.update(value=768), gr.update(value=256), gr.update(value=128), gr.update(visible=True), gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), gr.update(visible=True)]

                        train_mode_choose.change(update_train_mode, inputs=train_mode_choose, outputs=[resolution, rank, network_alpha, crop_ratio, training_prefix_prompt_row, val_and_checkpointing_steps, validation, enable_rl, rl_option_row1, rl_notes, skin_retouching_bool, human_train_notes, scene_train_notes, human_upload_note, scene_upload_note])

                with gr.Row():
                    with gr.Column(width=3):
                        run_button = gr.Button('Start Training')
                    with gr.Column(width=1):
                        refresh_button = gr.Button('Refresh Log')

                gr.Markdown(
                    '''
                    We need to train first to predict, please wait for the training to complete, thank you for your patience.  
                    '''
                )
                output_message  = gr.Markdown()

                with gr.Box():
                    logs_out        = gr.Chatbot(label='Training Logs', height=200)
                    block           = gr.Blocks()
                    with block:
                        block.load(refresh_display, None, logs_out, every=3)

                    refresh_button.click(
                        fn = refresh_display,
                        inputs = [],
                        outputs = [logs_out]
                    )

                run_button.click(fn=easyphoto_train_forward,
                                _js="ask_for_style_name",
                                inputs=[
                                    sd_model_checkpoint, dummy_component,
                                    uuid, train_mode_choose, 
                                    resolution, val_and_checkpointing_steps, max_train_steps, steps_per_photos, train_batch_size, gradient_accumulation_steps, dataloader_num_workers, learning_rate, rank, network_alpha, validation, instance_images,
                                    enable_rl, max_rl_time, timestep_fraction, skin_retouching_bool, 
                                    training_prefix_prompt, crop_ratio
                                ],
                                outputs=[output_message])
                                
        with gr.TabItem('Photo Inference'):
            dummy_component = gr.Label(visible=False)
            training_templates = glob.glob(os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "models"), 'training_templates/*.jpg'))
            infer_templates = glob.glob(os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "models"), 'infer_templates/*.jpg'))
            preset_template = list(training_templates) + list(infer_templates)

            with gr.Blocks() as demo:
                with gr.Row():
                    with gr.Column():
                        with gr.TabItem("Photo2Photo") as template_images_tab:
                            upload_way = gr.Radio(["Template Gallery", "Single Image Upload", "Batch Images Upload"], value="Template Gallery", show_label=False)

                            with gr.Column() as template_gallery:
                                template_gallery_list = [(i, i) for i in preset_template]
                                gallery = gr.Gallery(template_gallery_list).style(columns=[4], rows=[2], object_fit="contain", height="auto")
                                
                                def select_function(evt: gr.SelectData):
                                    return [preset_template[evt.index]]

                                selected_template_images = gr.Text(show_label=False, visible=False, placeholder="Selected")
                                gallery.select(select_function, None, selected_template_images)
                                
                            with gr.Column(visible=False) as single_image_upload:
                                init_image = gr.Image(label="Image for skybox", elem_id="{id_part}_image", show_label=False, source="upload")
                            
                            with gr.Column(visible=False) as batch_images_upload:
                                uploaded_template_images = gr.Gallery().style(columns=[4], rows=[2], object_fit="contain", height="auto")

                                with gr.Row():
                                    upload_dir_button = gr.UploadButton(
                                        "Upload Photos", file_types=["image"], file_count="multiple"
                                    )
                                    clear_dir_button = gr.Button("Clear Photos")
                                clear_dir_button.click(fn=lambda: [], inputs=None, outputs=uploaded_template_images)

                                upload_dir_button.upload(upload_file, inputs=[upload_dir_button, uploaded_template_images], outputs=uploaded_template_images, queue=False)
                            
                            def upload_way_change(upload_way):
                                if upload_way == "Template Gallery":
                                    return [gr.update(visible=True), gr.update(visible=False), gr.update(visible=False)]
                                elif upload_way == "Single Image Upload":
                                    return [gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)]
                                else:
                                    return [gr.update(visible=False), gr.update(visible=False), gr.update(visible=True)]

                            upload_way.change(upload_way_change, upload_way, [template_gallery, single_image_upload, batch_images_upload])
                            
                        with gr.TabItem("Text2Photo") as text2photo_tab:
                            with gr.Column():
                                text_to_image_input_prompt = gr.Textbox(
                                    label="Text2Photo Input Prompt", interactive=True, lines=2,
                                    value="(portrait:1.5), 1girl, bokeh, bouquet, brown_hair, cloud, flower, hairband, hydrangea, lips, long_hair, outdoors, sunlight, white_flower, white_rose, green sweater, sweater", visible=True
                                )
                                with gr.Accordion("Scene Lora (Click here to select Scene Lora)", open=False):
                                    with gr.Column():
                                        def scene_change_function(scene_id_gallery, evt: gr.SelectData):
                                            scene_id = scene_id_gallery[evt.index][1]
                                            # scene lora path
                                            lora_model_path = os.path.join(models_path, "Lora", f"{scene_id}.safetensors")
                                            if scene_id == "none":
                                                return gr.update(visible=True), gr.update(value="none")
                                            if scene_id in DEFAULT_SCENE_LORA:
                                                check_files_exists_and_download(False, download_mode=scene_id)
                                            if not os.path.exists(lora_model_path):
                                                return gr.update(value="Please check scene lora is exist or not."), gr.update(value="none")
                                            is_scene_lora, scene_lora_prompt = get_scene_prompt(lora_model_path)
                                            
                                            return gr.update(value=scene_lora_prompt), gr.update(value=scene_id)
                                        
                                        def scene_refresh_function():
                                            scene = [[os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "images"), "scene_lora", f'{_scene}.jpg'), _scene] for _scene in DEFAULT_SCENE_LORA]
                                            _scenes = os.listdir(os.path.join(models_path, "Lora"))
                                            for _scene in _scenes:
                                                if check_scene_valid(_scene, models_path):
                                                    if os.path.splitext(_scene)[0] in DEFAULT_SCENE_LORA:
                                                        continue
                                                    ref_image = os.path.join(models_path, "Lora", f"{os.path.splitext(_scene)[0]}.jpg")
                                                    if not os.path.exists(ref_image):
                                                        ref_image = os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "images"), 'no_found_image.jpg')
                                                    scene.append([ref_image, os.path.splitext(_scene)[0]])
                                            scene = sorted(scene)
                                            scene.insert(0, [os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "images"), 'no_found_image.jpg'), "none"])
                                            return gr.update(value=scene)
                                    
                                        scene = [[os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "images"), "scene_lora", f'{_scene}.jpg'), _scene] for _scene in DEFAULT_SCENE_LORA]
                                        _scenes = os.listdir(os.path.join(models_path, "Lora"))
                                        for _scene in _scenes:
                                            if check_scene_valid(_scene, models_path):
                                                if os.path.splitext(_scene)[0] in DEFAULT_SCENE_LORA:
                                                    continue
                                                ref_image = os.path.join(models_path, "Lora", f"{os.path.splitext(_scene)[0]}.jpg")
                                                if not os.path.exists(ref_image):
                                                    ref_image = os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "images"), 'no_found_image.jpg')
                                                scene.append([ref_image, os.path.splitext(_scene)[0]])
                                        scene = sorted(scene)
                                        scene.insert(0, [os.path.join(os.path.abspath(os.path.dirname(__file__)).replace("scripts", "images"), 'no_found_image.jpg'), "none"])

                                        scene_id = gr.Text(value="none", show_label=False, visible=True, placeholder="Selected", interactive=False)
                                        autodownload_notebook = gr.Markdown(value="**The preset Lora will be downloaded on the first click.**", show_label=False, visible=True)
                                        with gr.Row():
                                            scene_id_gallery = gr.Gallery(
                                                value=scene, label="Scene Lora Gallery", allow_preview=False, elem_id="scene_id_select", 
                                                show_share_button=False, visible=True
                                            ).style(columns=[5], rows=[2], object_fit="contain", height="auto")
                                            scene_id_gallery.select(scene_change_function, [scene_id_gallery], [text_to_image_input_prompt, scene_id])

                                            scene_id_refresh = ToolButton(value="\U0001f504")
                                            scene_id_refresh.click(fn=scene_refresh_function, inputs=[], outputs=[scene_id_gallery])

                                with gr.Row():
                                    text_to_image_width = gr.Slider(minimum=64, maximum=2048, step=8, label="Width", value=624, elem_id=f"width")
                                    text_to_image_height = gr.Slider(minimum=64, maximum=2048, step=8, label="Height", value=832,elem_id=f"height")

                                with gr.Row():
                                    prompt_generate_sd_model_checkpoint = gr.Dropdown(value="LZ-16K+Optics.safetensors", choices=list(set(["Chilloutmix-Ni-pruned-fp16-fix.safetensors"] + checkpoints + external_checkpoints)), label="The checkpoint you use for text to image prompt generate.", interactive=True, visible=True)

                                    prompt_generate_checkpoint_refresh = ToolButton(value="\U0001f504")
                                    prompt_generate_checkpoint_refresh.click(
                                        fn=checkpoint_refresh_function,
                                        inputs=[],
                                        outputs=[prompt_generate_sd_model_checkpoint]
                                    )

                                gr.Markdown(
                                    value = '''
                                        Generate from prompts notes:
                                        - The Generate from prompts is an experimental feature aiming to generate great portrait without template for users.
                                        - We use scene lora for background generation. So we need to train scene lora first.
                                    ''',
                                    visible=True
                                )

                        def generate_tabs(model_selected_tab, upload_way):
                            if model_selected_tab == 0:
                                tabs = {
                                    "Template Gallery"          : 0, 
                                    "Single Image Upload"       : 1,
                                    "Batch Images Upload"       : 2,
                                }[upload_way]
                            else:
                                tabs = 3
                            return tabs
                        
                        # get tabs
                        state_tab           = gr.State(0)
                        model_selected_tab  = gr.State(0)
                        model_selected_tabs = [template_images_tab, text2photo_tab]
                        for i, tab in enumerate(model_selected_tabs):
                            tab.select(fn=lambda tabnum=i: tabnum, inputs=[], outputs=[model_selected_tab])
                            tab.select(generate_tabs, [model_selected_tab, upload_way], state_tab)

                        upload_way.change(generate_tabs, [model_selected_tab, upload_way], state_tab)
                        
                        with gr.Row():
                            sd_model_checkpoint = gr.Dropdown(value="Chilloutmix-Ni-pruned-fp16-fix.safetensors", choices=list(set(["Chilloutmix-Ni-pruned-fp16-fix.safetensors"] + checkpoints + external_checkpoints)), label="The base checkpoint you use.", interactive=True, visible=True)

                            checkpoint_refresh = ToolButton(value="\U0001f504")
                            checkpoint_refresh.click(
                                fn=checkpoint_refresh_function,
                                inputs=[],
                                outputs=[sd_model_checkpoint]
                            )

                        with gr.Row():
                            infer_note = gr.Markdown(
                                value = "For faster speed, keep the same with Stable Diffusion checkpoint (in the upper left corner).",
                                visible=(sd_model_checkpoint.value != shared.opts.sd_model_checkpoint.split(" ")[0])
                            )
                        
                            def update_infer_note(sd_model_checkpoint):
                                # shared.opts.sd_model_checkpoint has a hash tag like "sd_xl_base_1.0.safetensors [31e35c80fc]".
                                if sd_model_checkpoint == shared.opts.sd_model_checkpoint.split(" ")[0]:
                                    return gr.Markdown.update(visible=False)
                                return gr.Markdown.update(visible=True)
                            
                            sd_model_checkpoint.change(fn=update_infer_note, inputs=sd_model_checkpoint, outputs=[infer_note])

                        with gr.Row():
                            def select_function():
                                ids = []
                                if os.path.exists(user_id_outpath_samples):
                                    _ids = os.listdir(user_id_outpath_samples)
                                    for _id in _ids:
                                        if check_id_valid(_id, user_id_outpath_samples, models_path):
                                            ids.append(_id)
                                ids = sorted(ids)
                                return gr.update(choices=["none"] + ids)

                            ids = []
                            if os.path.exists(user_id_outpath_samples):
                                _ids = os.listdir(user_id_outpath_samples)
                                for _id in _ids:
                                    if check_id_valid(_id, user_id_outpath_samples, models_path):
                                        ids.append(_id)
                                ids = sorted(ids)

                            num_of_faceid = gr.Dropdown(value=str(1), elem_id='dropdown', choices=[1, 2, 3, 4, 5], label=f"Num of Faceid")

                            uuids           = []
                            visibles        = [True, False, False, False, False]
                            for i in range(int(5)):
                                uuid = gr.Dropdown(value="none", elem_id='dropdown', choices=["none"] + ids, min_width=80, label=f"User_{i} id", visible=visibles[i])
                                uuids.append(uuid)

                            def update_uuids(_num_of_faceid):
                                _uuids = []
                                for i in range(int(_num_of_faceid)):
                                    _uuids.append(gr.update(value="none", visible=True))
                                for i in range(int(5 - int(_num_of_faceid))):
                                    _uuids.append(gr.update(value="none", visible=False))
                                return _uuids
                            
                            num_of_faceid.change(update_uuids, inputs=[num_of_faceid], outputs=uuids)
                            
                            refresh = ToolButton(value="\U0001f504")
                            for i in range(int(5)):
                                refresh.click(
                                    fn=select_function,
                                    inputs=[],
                                    outputs=[uuids[i]]
                                )

                        with gr.Accordion("Advanced Options", open=False):
                            additional_prompt = gr.Textbox(
                                label="Additional Prompt",
                                lines=3,
                                value='masterpiece, beauty',
                                interactive=True
                            )
                            seed = gr.Textbox(
                                label="Seed", 
                                value=-1,
                            )
                            with gr.Row():
                                before_face_fusion_ratio = gr.Slider(
                                    minimum=0.2, maximum=0.8, value=0.50,
                                    step=0.05, label='Face Fusion Ratio Before'
                                )
                                after_face_fusion_ratio = gr.Slider(
                                    minimum=0.2, maximum=0.8, value=0.50,
                                    step=0.05, label='Face Fusion Ratio After'
                                )

                            with gr.Row():
                                first_diffusion_steps = gr.Slider(
                                    minimum=15, maximum=50, value=50,
                                    step=1, label='First Diffusion steps'
                                )
                                first_denoising_strength = gr.Slider(
                                    minimum=0.30, maximum=0.60, value=0.45,
                                    step=0.05, label='First Diffusion denoising strength'
                                )
                            with gr.Row():
                                second_diffusion_steps = gr.Slider(
                                    minimum=15, maximum=50, value=20,
                                    step=1, label='Second Diffusion steps'
                                )
                                second_denoising_strength = gr.Slider(
                                    minimum=0.20, maximum=0.40, value=0.30,
                                    step=0.05, label='Second Diffusion denoising strength'
                                )
                            with gr.Row():
                                crop_face_preprocess = gr.Checkbox(
                                    label="Crop Face Preprocess",  
                                    value=True
                                )
                                apply_face_fusion_before = gr.Checkbox(
                                    label="Apply Face Fusion Before", 
                                    value=True
                                )
                                apply_face_fusion_after = gr.Checkbox(
                                    label="Apply Face Fusion After",  
                                    value=True
                                )
                            with gr.Row():
                                color_shift_middle = gr.Checkbox(
                                    label="Apply color shift first",  
                                    value=True
                                )
                                color_shift_last = gr.Checkbox(
                                    label="Apply color shift last",  
                                    value=True
                                )
                                super_resolution = gr.Checkbox(
                                    label="Super Resolution at last",  
                                    value=True
                                )
                            with gr.Row():
                                skin_retouching_bool = gr.Checkbox(
                                    label="Skin Retouching",  
                                    value=True
                                )
                                background_restore = gr.Checkbox(
                                    label="Background Restore",  
                                    value=False
                                )
                                makeup_transfer = gr.Checkbox(
                                    label="MakeUp Transfer",
                                    value=False
                                )
                            with gr.Row():
                                display_score = gr.Checkbox(
                                    label="Display Face Similarity Scores",  
                                    value=False
                                )
                                ip_adapter_control = gr.Checkbox(
                                    label="IP-Adapter Control",
                                    value=False
                                )
                                face_shape_match = gr.Checkbox(
                                    label="Face Shape Match",
                                    value=False
                                )

                                def ipa_update_score(ip_adapter_control, display_score):
                                    if not display_score and ip_adapter_control:
                                        return gr.Checkbox.update(value=True)
                                    return gr.Checkbox.update(value=display_score)
                                
                                def update_score(ip_adapter_control, display_score):
                                    if ip_adapter_control:
                                        return gr.Checkbox.update(value=True)
                                    return gr.Checkbox.update(value=display_score)
                                
                                # We need to make sure that Display Similarity Score is mandatory when the user
                                # selects IP-Adapter Control. Otherwise, it is not.
                                ip_adapter_control.change(
                                    ipa_update_score,
                                    inputs=[ip_adapter_control, display_score],
                                    outputs=[display_score]
                                )
                                display_score.change(
                                    update_score,
                                    inputs=[ip_adapter_control, display_score],
                                    outputs=[display_score]
                                )

                            with gr.Row():
                                super_resolution_method = gr.Dropdown(
                                    value="gpen", \
                                    choices=list(["gpen", "realesrgan"]), label="The super resolution way you use.", visible=True
                                )
                                background_restore_denoising_strength = gr.Slider(
                                    minimum=0.10, maximum=0.60, value=0.35,
                                    step=0.05, label='Background Restore Denoising Strength',
                                    visible=False
                                )
                                makeup_transfer_ratio = gr.Slider(
                                    minimum=0.00, maximum=1.00, value=0.50,
                                    step=0.05, label='Makeup Transfer Ratio',
                                    visible=False
                                )
                                ip_adapter_weight = gr.Slider(
                                    minimum=0.10, maximum=1.00, value=0.50,
                                    step=0.05, label="IP-Adapter Control Weight",
                                    visible=False
                                )
                                
                                super_resolution.change(lambda x: super_resolution_method.update(visible=x), inputs=[super_resolution], outputs=[super_resolution_method])
                                background_restore.change(lambda x: background_restore_denoising_strength.update(visible=x), inputs=[background_restore], outputs=[background_restore_denoising_strength])
                                makeup_transfer.change(lambda x: makeup_transfer_ratio.update(visible=x), inputs=[makeup_transfer], outputs=[makeup_transfer_ratio])
                                ip_adapter_control.change(lambda x: ip_adapter_weight.update(visible=x), inputs=[ip_adapter_control], outputs=[ip_adapter_weight])
                            
                            ipa_note = gr.Markdown(
                                value = '''
                                    IP-Adapter Control notes:
                                    1. If not uploaded, the reference image in the training photos will be used as the image prompt by default.
                                    2. For the best result, please upload a photo with a **frontal face and no occlusions** (bangs, glasses, etc.).
                                ''',
                                visible=False
                            )
                            with gr.Row():
                                ipa_image_path = gr.Image(label="Image Prompt for IP-Adapter Control", show_label=True, source="upload", type="filepath", visible=False)
                            ip_adapter_control.change(lambda x: ipa_image_path.update(visible=x), inputs=[ip_adapter_control], outputs=[ipa_image_path])
                            ip_adapter_control.change(lambda x: ipa_note.update(visible=x), inputs=[ip_adapter_control], outputs=[ipa_note])

                            with gr.Box():
                                gr.Markdown(
                                    '''
                                    Parameter parsing:
                                    1. **Face Fusion Ratio Before** represents the proportion of the first facial fusion, which is higher and more similar to the training object.  
                                    2. **Face Fusion Ratio After** represents the proportion of the second facial fusion, which is higher and more similar to the training object.  
                                    3. **Crop Face Preprocess** represents whether to crop the image before generation, which can adapt to images with smaller faces.  
                                    4. **Apply Face Fusion Before** represents whether to perform the first facial fusion.  
                                    5. **Apply Face Fusion After** represents whether to perform the second facial fusion. 
                                    6. **Skin Retouching** Whether to use skin retouching to postprocess generate face.
                                    7. **Display Face Similarity Scores** represents whether to compute the face similarity score of the generated image with the ID photo.
                                    8. **Background Restore** represents whether to give a different background.
                                    '''
                                )
                            
                        display_button = gr.Button('Start Generation')

                    with gr.Column():
                        gr.Markdown('Generated Results')

                        output_images = gr.Gallery(
                            label='Output',
                            show_label=False
                        ).style(columns=[4], rows=[2], object_fit="contain", height="auto")

                        with gr.Row():
                            tabname = 'easyphoto'
                            buttons = {
                                'img2img': ToolButton_webui('🖼️', elem_id=f'{tabname}_send_to_img2img', tooltip="Send image and generation parameters to img2img tab."),
                                'inpaint': ToolButton_webui('🎨️', elem_id=f'{tabname}_send_to_inpaint', tooltip="Send image and generation parameters to img2img inpaint tab."),
                                'extras': ToolButton_webui('📐', elem_id=f'{tabname}_send_to_extras', tooltip="Send image and generation parameters to extras tab.")
                            }

                        for paste_tabname, paste_button in buttons.items():
                            parameters_copypaste.register_paste_params_button(parameters_copypaste.ParamBinding(
                                paste_button=paste_button, tabname=paste_tabname, source_tabname="txt2img" if tabname == "txt2img" else None, source_image_component=output_images,
                                paste_field_names=[]
                            ))


                        face_id_text    = gr.Markdown("Face Similarity Scores", visible=False)
                        face_id_outputs = gr.Gallery(
                            label ="Face Similarity Scores",
                            show_label=False,
                            visible=False,
                        ).style(columns=[4], rows=[1], object_fit="contain", height="auto")
                        # Display Face Similarity Scores if the user intend to do it.
                        display_score.change(lambda x: face_id_text.update(visible=x), inputs=[display_score], outputs=[face_id_text])
                        display_score.change(lambda x: face_id_outputs.update(visible=x), inputs=[display_score], outputs=[face_id_outputs])

                        infer_progress = gr.Textbox(
                            label="Generation Progress",
                            value="No task currently",
                            interactive=False
                        )
                    
                display_button.click(
                    fn=easyphoto_infer_forward,
                    inputs=[
                        sd_model_checkpoint, selected_template_images, init_image, uploaded_template_images, \
                        text_to_image_input_prompt, text_to_image_width, text_to_image_height, scene_id, prompt_generate_sd_model_checkpoint, \
                        additional_prompt, before_face_fusion_ratio, after_face_fusion_ratio, \
                        first_diffusion_steps, first_denoising_strength, second_diffusion_steps, second_denoising_strength, \
                        seed, crop_face_preprocess, apply_face_fusion_before, apply_face_fusion_after, color_shift_middle, color_shift_last, super_resolution, super_resolution_method, skin_retouching_bool, display_score, \
                        background_restore, background_restore_denoising_strength, makeup_transfer, makeup_transfer_ratio, face_shape_match, state_tab, \
                        ip_adapter_control, ip_adapter_weight, ipa_image_path, *uuids
                    ],
                    outputs=[infer_progress, output_images, face_id_outputs]
                )
    
        with gr.TabItem('Video Inference'):
            dummy_component = gr.Label(visible=False)

            with gr.Blocks() as demo:
                with gr.Row():
                    with gr.Column():
                        video_model_selected_tab = gr.State(0)

                        with gr.TabItem("Text2Video") as video_template_images_tab:
                            t2v_input_prompt = gr.Textbox(
                                label="Text2Video Input Prompt.", interactive=True, lines=3,
                                value="1girl, (white hair, long hair), blue eyes, hair ornament, blue dress, standing, looking at viewer, shy, upper-body, ", visible=True
                            )
                            with gr.Row():
                                t2v_input_width = gr.Slider(minimum=64, maximum=2048, step=8, label="Video Width", value=512, elem_id=f"width")
                                t2v_input_height = gr.Slider(minimum=64, maximum=2048, step=8, label="Video Height", value=768,elem_id=f"height")

                            with gr.Row():
                                sd_model_checkpoint_for_animatediff_text2video = gr.Dropdown(value="majicmixRealistic_v7.safetensors", choices=list(set(["Chilloutmix-Ni-pruned-fp16-fix.safetensors"] + checkpoints + external_checkpoints)), elem_id='dropdown', min_width=40, label="The base checkpoint you use for Text2Video(For animatediff only).", visible=True)

                                checkpoint_refresh = ToolButton(value="\U0001f504")
                                checkpoint_refresh.click(
                                    fn=checkpoint_refresh_function,
                                    inputs=[],
                                    outputs=[sd_model_checkpoint_for_animatediff_text2video]
                                )
                                
                            gr.Markdown(
                                value = '''
                                Generate from prompts notes:
                                - We recommend using a more attractive portrait model such as **majicmixRealistic_v7** for video generation, which will result in better results !!!
                                - The Generate from prompts is an experimental feature aiming to generate great portrait without template for users.
                                ''',
                                visible=True
                            )

                        with gr.TabItem("Image2Video") as video_upload_image_tab:
                            i2v_mode_choose     = gr.Dropdown(value="Base on One Image", elem_id='dropdown', choices=["Base on One Image", "From One Image to another"], label="Generate video from one image or more images", visible=True)
                            
                            with gr.Row():
                                init_image      = gr.Image(label="Image for easyphoto to Image2Video", show_label=True, elem_id="{id_part}_image", source="upload")
                                last_image      = gr.Image(label="Last image for easyphoto to Image2Video", show_label=True, elem_id="{id_part}_image", source="upload", visible=False)
                            init_image_prompt   = gr.Textbox(label="Prompt For Image2Video", value="", show_label=True, visible=True, placeholder="Please write the corresponding prompts using the template.")
                            
                            def update_i2v_mode(i2v_mode_choose):
                                if i2v_mode_choose == "Base on One Image":
                                    return [
                                        gr.update(label="Image for easyphoto to Image2Video", value=None, visible=True), \
                                        gr.update(value=None, visible=False)
                                    ]
                                else:
                                    return [
                                        gr.update(label="First Image for easyphoto to Image2Video", value=None, visible=True), \
                                        gr.update(value=None, visible=True)
                                    ]
                            i2v_mode_choose.change(update_i2v_mode, inputs=i2v_mode_choose, outputs=[init_image, last_image])

                            with gr.Row():
                                sd_model_checkpoint_for_animatediff_image2video = gr.Dropdown(value="majicmixRealistic_v7.safetensors", choices=list(set(["Chilloutmix-Ni-pruned-fp16-fix.safetensors"] + checkpoints + external_checkpoints)), elem_id='dropdown', min_width=40, label="The base checkpoint you use for Image2Video(For animatediff only).", visible=True)

                                checkpoint_refresh = ToolButton(value="\U0001f504")
                                checkpoint_refresh.click(
                                    fn=checkpoint_refresh_function,
                                    inputs=[],
                                    outputs=[sd_model_checkpoint_for_animatediff_image2video]
                                )
                            gr.Markdown(
                                value = '''
                                Generate from image notes:
                                - We recommend using a more attractive portrait model such as **majicmixRealistic_v7** for video generation, which will result in better results!!!
                                - **Please write the corresponding prompts using the template**.
                                - The Generate from prompts is an experimental feature aiming to generate great portrait with template for users.
                                ''',
                                visible=True
                            )

                        with gr.TabItem("Video2Video") as video_upload_video_tab:
                            init_video = gr.Video(label="Video for easyphoto to V2V", show_label=True, elem_id="{id_part}_video", source="upload")

                        model_selected_tabs = [video_template_images_tab, video_upload_image_tab, video_upload_video_tab]
                        for i, tab in enumerate(model_selected_tabs):
                            tab.select(fn=lambda tabnum=i: tabnum, inputs=[], outputs=[video_model_selected_tab])

                        with gr.Row():
                            sd_model_checkpoint = gr.Dropdown(value="Chilloutmix-Ni-pruned-fp16-fix.safetensors", choices=list(set(["Chilloutmix-Ni-pruned-fp16-fix.safetensors"] + checkpoints + external_checkpoints)), label="The base checkpoint you use.", visible=True)

                            checkpoint_refresh = ToolButton(value="\U0001f504")
                            checkpoint_refresh.click(
                                fn=checkpoint_refresh_function,
                                inputs=[],
                                outputs=[sd_model_checkpoint]
                            )

                        with gr.Row():
                            def select_function():
                                ids = []
                                if os.path.exists(user_id_outpath_samples):
                                    _ids = os.listdir(user_id_outpath_samples)
                                    for _id in _ids:
                                        if check_id_valid(_id, user_id_outpath_samples, models_path):
                                            ids.append(_id)
                                ids = sorted(ids)
                                return gr.update(choices=["none"] + ids)

                            ids = []
                            if os.path.exists(user_id_outpath_samples):
                                _ids = os.listdir(user_id_outpath_samples)
                                for _id in _ids:
                                    if check_id_valid(_id, user_id_outpath_samples, models_path):
                                        ids.append(_id)
                                ids = sorted(ids)

                            num_of_faceid = gr.Dropdown(value=str(1), elem_id='dropdown', choices=[1, 2, 3, 4, 5], label=f"Num of Faceid", visible=False)

                            uuids           = []
                            visibles        = [True, False, False, False, False]
                            for i in range(int(5)):
                                uuid = gr.Dropdown(value="none", elem_id='dropdown', choices=["none"] + ids, min_width=80, label=f"User_{i} id", visible=visibles[i])
                                uuids.append(uuid)

                            def update_uuids(_num_of_faceid):
                                _uuids = []
                                for i in range(int(_num_of_faceid)):
                                    _uuids.append(gr.update(value="none", visible=True))
                                for i in range(int(5 - int(_num_of_faceid))):
                                    _uuids.append(gr.update(value="none", visible=False))
                                return _uuids
                            
                            num_of_faceid.change(update_uuids, inputs=[num_of_faceid], outputs=uuids)
                            
                            refresh = ToolButton(value="\U0001f504")
                            for i in range(int(5)):
                                refresh.click(
                                    fn=select_function,
                                    inputs=[],
                                    outputs=[uuids[i]]
                                )

                        with gr.Accordion("Advanced Options", open=False):
                            additional_prompt = gr.Textbox(
                                label="Video Additional Prompt",
                                lines=3,
                                value='masterpiece, beauty',
                                interactive=True
                            )
                            seed = gr.Textbox(
                                label="Video Seed", 
                                value=-1,
                            )
                            with gr.Row():
                                max_frames = gr.Textbox(
                                    label="Video Max frames", 
                                    value=32,
                                )
                                max_fps = gr.Textbox(
                                    label="Video Max fps", 
                                    value=8,
                                )
                                save_as = gr.Dropdown(
                                    value="gif", elem_id='dropdown', choices=["gif", "mp4"], min_width=30, label=f"Video Save as", visible=True
                                )

                            with gr.Row():
                                before_face_fusion_ratio = gr.Slider(
                                    minimum=0.2, maximum=0.8, value=0.50,
                                    step=0.05, label='Video Face Fusion Ratio Before'
                                )
                                after_face_fusion_ratio = gr.Slider(
                                    minimum=0.2, maximum=0.8, value=0.50,
                                    step=0.05, label='Video Face Fusion Ratio After'
                                )

                            with gr.Row():
                                first_diffusion_steps = gr.Slider(
                                    minimum=15, maximum=50, value=50,
                                    step=1, label='Video First Diffusion steps'
                                )
                                first_denoising_strength = gr.Slider(
                                    minimum=0.30, maximum=0.60, value=0.45,
                                    step=0.05, label='Video First Diffusion denoising strength'
                                )
                            with gr.Row():
                                crop_face_preprocess = gr.Checkbox(
                                    label="Video Crop Face Preprocess",  
                                    value=True
                                )
                                apply_face_fusion_before = gr.Checkbox(
                                    label="Video Apply Face Fusion Before", 
                                    value=True
                                )
                                apply_face_fusion_after = gr.Checkbox(
                                    label="Video Apply Face Fusion After",  
                                    value=True
                                )
                            with gr.Row():
                                color_shift_middle = gr.Checkbox(
                                    label="Video Apply color shift first",  
                                    value=True
                                )
                                super_resolution = gr.Checkbox(
                                    label="Video Super Resolution at last",  
                                    value=True
                                )
                                skin_retouching_bool = gr.Checkbox(
                                    label="Video Skin Retouching",  
                                    value=False
                                )
                            with gr.Row():
                                display_score = gr.Checkbox(
                                    label="Display Face Similarity Scores",  
                                    value=False
                                )
                                makeup_transfer = gr.Checkbox(
                                    label="Video MakeUp Transfer",
                                    value=False
                                )
                                face_shape_match = gr.Checkbox(
                                    label="Video Face Shape Match",
                                    value=False
                                )
                            with gr.Row():
                                video_interpolation = gr.Checkbox(
                                    label="Video Interpolation",
                                    value=False
                                )

                            with gr.Row():
                                super_resolution_method = gr.Dropdown(
                                    value="gpen", \
                                    choices=list(["gpen", "realesrgan"]), label="The video super resolution way you use.", visible=True
                                )
                                makeup_transfer_ratio = gr.Slider(
                                    minimum=0.00, maximum=1.00, value=0.50,
                                    step=0.05, label='Video Makeup Transfer Ratio',
                                    visible=False
                                )
                                super_resolution.change(lambda x: super_resolution_method.update(visible=x), inputs=[super_resolution], outputs=[super_resolution_method])
                                makeup_transfer.change(lambda x: makeup_transfer_ratio.update(visible=x), inputs=[makeup_transfer], outputs=[makeup_transfer_ratio])

                            with gr.Row():
                                video_interpolation_ext = gr.Slider(
                                    minimum=1, maximum=2, value=1,
                                    step=1, label='Video Interpolation Ratio (1 for 2x, 2 for 4x)',
                                    visible=False
                                )
                                video_interpolation.change(lambda x: video_interpolation_ext.update(visible=x), inputs=[video_interpolation], outputs=[video_interpolation_ext])

                            with gr.Box():
                                gr.Markdown(
                                    '''
                                    Parameter parsing:
                                    1. **Face Fusion Ratio Before** represents the proportion of the first facial fusion, which is higher and more similar to the training object.  
                                    2. **Face Fusion Ratio After** represents the proportion of the second facial fusion, which is higher and more similar to the training object.  
                                    3. **Apply Face Fusion Before** represents whether to perform the first facial fusion.  
                                    4. **Apply Face Fusion After** represents whether to perform the second facial fusion. 
                                    5. **Skin Retouching** Whether to use skin retouching to postprocess generate face.
                                    '''
                                )
                            
                        display_button = gr.Button('Start Generation')

                    with gr.Column():
                        gr.Markdown('Generated Results')

                        output_video    = gr.Video(label='Output of Video', visible=False)
                        output_gif      = gr.Image(label='Output of GIF')

                        def update_save_as_mode(save_as_mode):
                            if save_as_mode == "mp4":
                                return [gr.update(visible=True), gr.update(visible=False)]
                            else:
                                return [gr.update(visible=False), gr.update(visible=True)]
                            
                        save_as.change(update_save_as_mode, [save_as], [output_video, output_gif])
                                
                        output_images = gr.Gallery(
                            label='Output Frames',
                        ).style(columns=[4], rows=[2], object_fit="contain", height="auto")

                        infer_progress = gr.Textbox(
                            label="Generation Progress",
                            value="No task currently",
                            interactive=False
                        )
                        with gr.Row():
                            def save_video():
                                origin_path = os.path.join(easyphoto_video_outpath_samples, "origin")
                                crop_path = os.path.join(easyphoto_video_outpath_samples, "crop")
                                if not os.path.exists(origin_path):
                                    os.makedirs(origin_path, exist_ok=True)
                                index = len([path for path in os.listdir(origin_path)]) + 1

                                video_path = []
                                video_crop_path = []
                                for sub_index in range(max(index - 3, 0), index):
                                    video_mp4_path = os.path.join(origin_path, str(sub_index).zfill(8) + '.mp4')
                                    video_gif_path = os.path.join(origin_path, str(sub_index).zfill(8) + '.gif')
                                    for _video_path in [video_mp4_path, video_gif_path]:
                                        if os.path.exists(_video_path):
                                            video_path.append(_video_path)
                                            continue

                                    video_mp4_crop_path = os.path.join(crop_path, str(sub_index).zfill(8) + "_crop" + '.mp4')
                                    video_gif_crop_path = os.path.join(crop_path, str(sub_index).zfill(8) + "_crop" + '.gif')
                                    for _video_path in [video_mp4_crop_path, video_gif_crop_path]:
                                        if os.path.exists(_video_path):
                                            video_crop_path.append(_video_path)
                                            continue
                                return gr.File.update(value=video_path, visible=True), gr.File.update(value=video_crop_path, visible=True)

                            save = gr.Button('List Recent Conversion Results', elem_id=f'save')
                            download_origin_files = gr.File(None, label='Download Files For Origin Video', file_count="multiple", interactive=False, show_label=True, visible=False, elem_id=f'download_files')
                            download_crop_files = gr.File(None, label='Download Files For Cropped Video', file_count="multiple", interactive=False, show_label=True, visible=False, elem_id=f'download_files')
                            save.click(fn=save_video, inputs=None, outputs=[download_origin_files, download_crop_files], show_progress=False)
                    
                display_button.click(
                    fn=easyphoto_video_infer_forward,
                    inputs=[sd_model_checkpoint, sd_model_checkpoint_for_animatediff_text2video, sd_model_checkpoint_for_animatediff_image2video, \
                            t2v_input_prompt, t2v_input_width, t2v_input_height, init_image, init_image_prompt, last_image, init_video, additional_prompt, max_frames, max_fps, save_as, before_face_fusion_ratio, after_face_fusion_ratio, \
                            first_diffusion_steps, first_denoising_strength, seed, crop_face_preprocess, apply_face_fusion_before, apply_face_fusion_after, \
                            color_shift_middle, super_resolution, super_resolution_method, skin_retouching_bool, display_score, \
                            makeup_transfer, makeup_transfer_ratio, face_shape_match, video_interpolation, video_interpolation_ext, video_model_selected_tab, *uuids],
                    outputs=[infer_progress, output_video, output_gif, output_images]
                )

    return [(easyphoto_tabs, "EasyPhoto", f"EasyPhoto_tabs")]

# Configuration items for registration settings page
def on_ui_settings():
    section = ('EasyPhoto', "EasyPhoto")
    shared.opts.add_option("easyphoto_cache_model", shared.OptionInfo(
        True, "Cache preprocess model in Inference", gr.Checkbox, {}, section=section))

script_callbacks.on_ui_settings(on_ui_settings)  # 注册进设置页
script_callbacks.on_ui_tabs(on_ui_tabs)
