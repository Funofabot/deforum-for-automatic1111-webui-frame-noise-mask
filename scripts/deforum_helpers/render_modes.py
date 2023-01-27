import os
import pathlib
import json
from .render import render_animation
from .seed import next_seed
from .vid2frames import vid2frames
from .prompt import interpolate_prompts
from .generate import generate
from .animation_key_frames import DeformAnimKeys
from .parseq_adapter import ParseqAnimKeys
from .save_images import save_image

# Webui
from modules.shared import opts, cmd_opts, state

def render_input_video(args, anim_args, video_args, parseq_args, animation_prompts, root):
    # create a folder for the video input frames to live in
    video_in_frame_path = os.path.join(args.outdir, 'inputframes') 
    os.makedirs(video_in_frame_path, exist_ok=True)

    # save the video frames from input video
    print(f"Exporting Video Frames (1 every {anim_args.extract_nth_frame}) frames to {video_in_frame_path}...")
    vid2frames(anim_args.video_init_path, video_in_frame_path, anim_args.extract_nth_frame, anim_args.overwrite_extracted_frames, anim_args.extract_from_frame, anim_args.extract_to_frame, False)

    # determine max frames from length of input frames
    anim_args.max_frames = len([f for f in pathlib.Path(video_in_frame_path).glob('*.jpg')])
    args.use_init = True
    print(f"Loading {anim_args.max_frames} input frames from {video_in_frame_path} and saving video frames to {args.outdir}")

    if anim_args.use_mask_video:
        # create a folder for the mask video input frames to live in
        mask_in_frame_path = os.path.join(args.outdir, 'maskframes') 
        os.makedirs(mask_in_frame_path, exist_ok=True)

        # save the video frames from mask video
        print(f"Exporting Video Frames (1 every {anim_args.extract_nth_frame}) frames to {mask_in_frame_path}...")
        vid2frames(anim_args.video_mask_path, mask_in_frame_path, anim_args.extract_nth_frame, anim_args.overwrite_extracted_frames, anim_args.extract_from_frame, anim_args.extract_to_frame, False)
        max_mask_frames = len([f for f in pathlib.Path(mask_in_frame_path).glob('*.jpg')])

        # limit max frames if there are less frames in the video mask compared to input video
        if max_mask_frames < anim_args.max_frames :
            anim_args.max_mask_frames
            print ("Video mask contains less frames than init video, max frames limited to number of mask frames.")
        args.use_mask = True
        args.overlay_mask = True


    render_animation(args, anim_args, video_args, parseq_args, animation_prompts, root)

# Modified a copy of the above to allow using masking video with out a init video.
def render_animation_with_video_mask(args, anim_args, video_args, parseq_args, animation_prompts, root):
    # create a folder for the video input frames to live in
    mask_in_frame_path = os.path.join(args.outdir, 'maskframes') 
    os.makedirs(mask_in_frame_path, exist_ok=True)

    # save the video frames from mask video
    print(f"Exporting Video Frames (1 every {anim_args.extract_nth_frame}) frames to {mask_in_frame_path}...")
    vid2frames(anim_args.video_mask_path, mask_in_frame_path, anim_args.extract_nth_frame, anim_args.overwrite_extracted_frames, anim_args.extract_from_frame, anim_args.extract_to_frame, False)
    args.use_mask = True
    #args.overlay_mask = True

    # determine max frames from length of input frames
    anim_args.max_frames = len([f for f in pathlib.Path(mask_in_frame_path).glob('*.jpg')])
    #args.use_init = True
    print(f"Loading {anim_args.max_frames} input frames from {mask_in_frame_path} and saving video frames to {args.outdir}")

    render_animation(args, anim_args, video_args, parseq_args, animation_prompts, root)


def render_interpolation(args, anim_args, video_args, parseq_args, animation_prompts, root):

    # use parseq if manifest is provided
    use_parseq = parseq_args.parseq_manifest != None and parseq_args.parseq_manifest.strip()

    # expand key frame strings to values
    keys = DeformAnimKeys(anim_args) if not use_parseq else ParseqAnimKeys(parseq_args, anim_args)

    # create output folder for the batch
    os.makedirs(args.outdir, exist_ok=True)
    print(f"Saving interpolation animation frames to {args.outdir}")

    # save settings for the batch
    settings_filename = os.path.join(args.outdir, f"{args.timestring}_settings.txt")
    with open(settings_filename, "w+", encoding="utf-8") as f:
        s = {**dict(args.__dict__), **dict(anim_args.__dict__), **dict(parseq_args.__dict__)}
        json.dump(s, f, ensure_ascii=False, indent=4)
    
    # Compute interpolated prompts
    if use_parseq:
        print("Parseq prompts are assumed to already be interpolated - not doing any additional prompt interpolation")
        prompt_series = keys.prompts
    else: 
        print("Generating interpolated prompts for all frames")
        prompt_series = interpolate_prompts(animation_prompts, anim_args.max_frames)
    
    state.job_count = anim_args.max_frames
    frame_idx = 0
    while frame_idx < anim_args.max_frames:
        print(f"Rendering interpolation animation frame {frame_idx} of {anim_args.max_frames}")
        state.job = f"frame {frame_idx + 1}/{anim_args.max_frames}"
        state.job_no = frame_idx + 1
        
        if state.interrupted:
                break
        
        # grab inputs for current frame generation
        args.n_samples = 1
        args.prompt = prompt_series[frame_idx]
        args.scale = keys.cfg_scale_schedule_series[frame_idx]
        
        if anim_args.enable_checkpoint_scheduling:
            args.checkpoint = keys.checkpoint_schedule_series[frame_idx]
            print(f"Checkpoint changed to: {args.checkpoint}")
        else:
            args.checkpoint = None
            
        if use_parseq:
            args.seed_enable_extras = True
            args.subseed = int(keys.subseed_series[frame_idx])
            args.subseed_strength = keys.subseed_strength_series[frame_idx]
            
        if args.seed_behavior == 'schedule' or use_parseq:
            args.seed = int(keys.seed_schedule_series[frame_idx])
        
        image = generate(args, anim_args, root, frame_idx)
        filename = f"{args.timestring}_{frame_idx:05}.png"

        save_image(image, 'PIL', filename, args, video_args, root)

        state.current_image = image
        
        if args.seed_behavior != 'schedule':
            args.seed = next_seed(args)

        frame_idx += 1