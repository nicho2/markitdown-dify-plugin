from collections.abc import Generator
from typing import Any
import tempfile
import os

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from markitdown import MarkItDown

from types import MethodType
import httpx


class FileWrapper:
    def __init__(self, file_pydantic):
        self._file = file_pydantic

def my_blob(self) -> bytes:
    """
    Get the file content as a bytes object.

    If the file content is not loaded yet, it will be loaded from the URL and stored in the `_blob` attribute.
    """
    if self._file._blob is None:
        response = httpx.get(self._file.url,verify=False)
        response.raise_for_status()
        self._file._blob = response.content

    assert self._file._blob is not None
    return self._file._blob



class MarkitdownTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        files = tool_parameters.get('files', [])

        # Handle empty files array
        if not files:
            yield self.create_text_message("No files provided")
            yield self.create_json_message({
                "status": "error",
                "message": "No files provided",
                "results": []
            })
            return

        results = []
        json_results = []

        # Process each file
        for file in files:
            try:
                file_extension = file.extension if file.extension else '.tmp'

                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                    # Liaison de la fonction à l'instance file uniquement
                    my_file = FileWrapper(file)
                    my_file.my_blob = MethodType(my_blob, my_file)
                    temp_file.write(my_file.my_blob())
                    temp_file_path = temp_file.name
                try:
                    md = MarkItDown()
                    result = md.convert(temp_file_path)

                    # Create blob message for backward compatibility
                    yield self.create_blob_message(
                        result.text_content.encode(),
                        meta={
                            "mime_type": "text/markdown",
                        },
                    )

                    if result and hasattr(result, 'text_content'):
                        results.append({
                            "filename": file.filename,
                            "content": result.text_content
                        })

                        # Add to JSON results
                        json_results.append({
                            "filename": file.filename,
                            "original_format": file_extension.lstrip('.'),
                            "markdown_content": result.text_content,
                            "status": "success"
                        })
                    else:
                        error_msg = f"Conversion failed for file {file.filename}. Result: {result}"
                        yield self.create_text_message(text=error_msg)
                        json_results.append({
                            "filename": file.filename,
                            "original_format": file_extension.lstrip('.'),
                            "error": error_msg,
                            "status": "error"
                        })

                finally:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)

            except Exception as e:
                error_msg = f"Error processing file {file.filename}: {str(e)}"
                yield self.create_text_message(text=error_msg)
                json_results.append({
                    "filename": file.filename,
                    "original_format": file_extension.lstrip('.'),
                    "error": error_msg,
                    "status": "error"
                })

        # Create JSON response
        json_response = {
            "status": "success" if len(results) > 0 else "error",
            "total_files": len(files),
            "successful_conversions": len(results),
            "results": json_results
        }
        yield self.create_json_message(json_response)

        # Return text results based on number of files processed (for backward compatibility)
        if len(results) == 0:
            yield self.create_text_message("No files were successfully processed")
        elif len(results) == 1:
            yield self.create_text_message(results[0]["content"])
        else:
            combined_content = ""
            for idx, result in enumerate(results, 1):
                combined_content += f"\n{'=' * 50}\n"
                combined_content += f"File {idx}: {result['filename']}\n"
                combined_content += f"{'=' * 50}\n\n"
                combined_content += result['content']
                combined_content += "\n\n"

            yield self.create_text_message(combined_content.strip())
