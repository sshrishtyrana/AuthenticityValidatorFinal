import torch
from PIL import Image

from transformers import (
    RobertaTokenizer,
    ViTImageProcessor,
    VisionEncoderDecoderModel
)


class HandwritingOCR:

    def __init__(
        self,
        model_name="microsoft/trocr-base-handwritten"
    ):

        self.device = (
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )

        self.image_processor = (
            ViTImageProcessor.from_pretrained(
                model_name
            )
        )

        self.tokenizer = RobertaTokenizer.from_pretrained(
            model_name
        )

        self.model = (
            VisionEncoderDecoderModel.from_pretrained(
                model_name
            )
        )

        self.model.config.decoder_start_token_id = (
            self.tokenizer.cls_token_id
        )

        self.model.config.pad_token_id = (
            self.tokenizer.pad_token_id
        )

        self.model.config.eos_token_id = (
            self.tokenizer.sep_token_id
        )

        self.model.to(self.device)

        self.model.eval()

    def recognize(self, image_path: str) -> str:

        image = Image.open(
            image_path
        ).convert("RGB")

        pixel_values = self.image_processor(
            images=image,
            return_tensors="pt"
        ).pixel_values

        pixel_values = pixel_values.to(
            self.device
        )

        with torch.no_grad():

            generated_ids = self.model.generate(
                pixel_values
            )

        text = self.tokenizer.batch_decode(
            generated_ids,
            skip_special_tokens=True
        )[0]

        return text.strip()