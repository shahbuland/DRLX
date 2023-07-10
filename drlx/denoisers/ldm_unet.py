from torchtyping import TensorType
from typing import Iterable, Union

import torch
import numpy as np
from diffusers import UNet2DConditionModel

from drlx.denoisers import BaseConditionalDenoiser
from drlx.configs import ModelConfig, SamplerConfig
from drlx.sampling import Sampler

class LDMUNet(BaseConditionalDenoiser):
    def __init__(self, config : ModelConfig, sampler_config : SamplerConfig = None, sampler : Sampler = None):
        super().__init__(config, sampler_config, sampler)

        self.unet : UNet2DConditionModel = None
        self.text_encoder = None
        self.vae = None

        self.tokenizer = None
        self.scheduler = None

        self.scale_factor = None

    def get_input_shape(self):
        assert self.unet and self.vae, "Cannot get input shape if model not initialized"

        in_channels = self.unet.in_channels
        sample_size = self.config.img_size // self.scale_factor

        return (in_channels, sample_size, sample_size)
    
    def from_pretrained_pipeline(self, cls, path):
        """
        Get unet from some pretrained model pipeline
        """
        pipe = cls.from_pretrained(path)
        self.unet = pipe.unet

        self.text_encoder = pipe.text_encoder
        self.vae = pipe.vae
        self.scale_factor = pipe.vae_scale_factor
        self.vae = self.vae.to(self.config.vae_device)

        self.text_encoder.requires_grad_(False)
        self.vae.requires_grad_(False)

        self.tokenizer = pipe.tokenizer
        self.scheduler = pipe.scheduler

        return self
    
    def preprocess(self, text : Iterable[str]):
        tok_out = self.tokenizer(
            text,
            padding = 'max_length',
            max_length = self.tokenizer.model_max_length,
            truncation = True,
            return_tensors = "pt"
        )
        return tok_out.input_ids, tok_out.attention_mask

    @torch.no_grad()
    def postprocess(self, output : TensorType["batch", "channels", "height", "width"]):
        images = self.vae.decode(1 / 0.18215 * output.cuda()).sample
        images = (images / 2 + 0.5).clamp(0, 1)
        images = images.detach().cpu().permute(0,2,3,1).numpy()
        images = (images * 255).round().astype(np.uint8)
        return images

    def forward(
            self,
            pixel_values : TensorType["batch", "channels", "height", "width"],
            input_ids : TensorType["batch", "seq_len"],
            attention_mask : TensorType["batch", "seq_len"],
            time_step : Union[TensorType["batch"], int] # Note diffusers tyically does 999->0 as steps
        ):
        """
        For text conditioned UNET, inputs are assumed to be:
        pixel_values, input_ids, attention_mask, time_step
        """
        with torch.no_grad():
            text_embeds = self.text_encoder(input_ids, attention_mask)[0]

        return self.unet(
            pixel_values,
            time_step,
            encoder_hidden_states = text_embeds
        )
    

        