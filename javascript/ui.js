function ask_for_style_name(sd_model_checkpoint, dummy_component, _, resolution, val_and_checkpointing_steps, max_train_steps, steps_per_photos, train_batch_size, gradient_accumulation_steps, dataloader_num_workers, learning_rate, rank, network_alpha, validation, main_image, instance_images, enable_rl, max_rl_time, timestep_fraction, refine_mask,use_mask) {
    var name_ = prompt('User id:');
    return [sd_model_checkpoint, dummy_component, name_, resolution, val_and_checkpointing_steps, max_train_steps, steps_per_photos, train_batch_size, gradient_accumulation_steps, dataloader_num_workers, learning_rate, rank, network_alpha, validation, main_image, instance_images, enable_rl, max_rl_time, timestep_fraction,refine_mask,use_mask, ];
}

function ask_for_add_new_user_id(name, reference_image, reference_mask) {
    var user_id = prompt('User id:');
    return [user_id, reference_image, reference_mask];
}