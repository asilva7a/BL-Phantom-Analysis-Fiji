import os
import csv
import traceback
from ij import IJ, WindowManager
from ij.plugin import ImageCalculator, ZProjector
from ij.plugin.filter import GaussianBlur, ParticleAnalyzer, Analyzer
from ij.measure import ResultsTable
from ij.process import ImageConverter
from ij.measure import Measurements
from ij.plugin.frame import RoiManager
from ij.process import ImageProcessor

# Define parameters for the script, to be set by the user in ImageJ
#@ File    (label = "Input directory", style = "directory") srcFile
#@ File    (label = "Output directory", style = "directory") dstFile
#@ File    (label = "Background image file") backgroundFile
#@ String  (label = "File extension", value=".tif") ext
#@ String  (label = "File name contains", value = "") containString
#@ boolean (label = "Keep directory structure when saving", value = True) keepDirectories
#@ String  (label = "Filter files by name (leave empty for no filter)", value = "") fileFilter
#@ File    (label = "CSV output directory", style = "directory") csvOutputDir

def run():
    srcDir = srcFile.getAbsolutePath()
    dstDir = dstFile.getAbsolutePath()
    backgroundImagePath = backgroundFile.getAbsolutePath()

    for root, directories, fileNames in os.walk(srcDir):
        for fileName in fileNames:
            if fileFilter and fileFilter not in fileName:
                continue  # Skip files that don't contain the specified filter text
            print("Processing file:", fileName)
            if fileName.endswith(ext):
                file_path = os.path.join(root, fileName)
                print("Processing file:", file_path)
                try:
                    process(srcDir, dstDir, root, fileName, backgroundImagePath)
                    print("Finished processing file:", file_path)
                except Exception as e:
                    traceback.print_exc()

    # Close the measurements window after processing all images
    close_measurements_window()
    
# Function to close the measurements window
def close_measurements_window():
    if WindowManager.getWindow("Results") is not None:
        WindowManager.getWindow("Results").close()
        print("Results window closed.")

def sum_slices(imp):
    try:
        zp = ZProjector(imp)
        zp.setMethod(ZProjector.SUM_METHOD)
        zp.doProjection()
        return zp.getProjection()
    except Exception as e:
        error_message = "Error in sum_slices: {}".format(str(e))
        print(error_message)
        return None

# Process function
def process(srcDir, dstDir, currentDir, fileName, backgroundImagePath):
    try:
        imagePath = os.path.join(currentDir, fileName)
        print("File Name: " + fileName)
        print("Image path: " + imagePath)
        print("Processing file: " + imagePath)
        imp = open_image(imagePath)
        if imp is None:
            print("Failed to open image: " + imagePath)
            return

        background_imp = open_image(backgroundImagePath)
        if background_imp is None:
            print("Failed to open background image: " + backgroundImagePath)
            return

        result_imp = subtract_background(imp, background_imp)
        if result_imp is not None:
            result_imp = remove_outliers(result_imp)
            result_imp = apply_gaussian_blur(result_imp)
            summed_imp = sum_slices(result_imp)
            if summed_imp is not None:
                roi = determine_roi(summed_imp)

                if roi is not None:
                    measurements = apply_roi_and_measure(result_imp, roi)
                    # Save CSV files to the specified directory
                    save_measurements_to_csv(measurements, csvOutputDir.getAbsolutePath(), fileName)

                save_processed_image(result_imp, srcDir, dstDir, currentDir, fileName)
    except Exception as e:
        print("Error in process function for " + fileName + ": " + str(e))

# Function to open an image using ImageJ
def open_image(imagePath):
    print("Open image file: " + imagePath)
    imp = IJ.openImage(imagePath)
    if imp is None:
        print("Could not open image: " + imagePath)
    return imp

# Function to subtract the background from an image
def subtract_background(imp, background_imp):
    ic = ImageCalculator()
    return ic.run("Subtract create stack", imp, background_imp)

# Function to remove outliers from an image
def remove_outliers(imp):
    IJ.run(imp, "Remove Outliers", "radius=2 threshold=50 which=Bright stack")
    return imp

# Function to apply Gaussian blur to an image
def apply_gaussian_blur(imp, sigma=2.0):
    stack = imp.getStack()
    gb = GaussianBlur()
    for i in range(1, stack.getSize() + 1):
        ip = stack.getProcessor(i)
        gb.blurGaussian(ip, sigma, sigma, 0.01)
        stack.setProcessor(ip, i)
    imp.setStack(stack)
    return imp

# Function to determine the ROI based on the summed image
def determine_roi(summed_imp):
    ImageConverter(summed_imp).convertToGray8()
    ip = summed_imp.getProcessor()
    ip.setAutoThreshold("Triangle dark")
    if ip.getMinThreshold() == ImageProcessor.NO_THRESHOLD:
        print("Warning: Triangle thresholding failed, applying a manual threshold.")
        ip.setThreshold(50, 255, ImageProcessor.NO_LUT_UPDATE)
    IJ.run(summed_imp, "Convert to Mask", "")
    rt = ResultsTable()
    pa = ParticleAnalyzer(ParticleAnalyzer.ADD_TO_MANAGER, Measurements.AREA, rt, 50.0, float('inf'), 0.0, 1.0)
    pa.analyze(summed_imp)
    roiManager = RoiManager.getInstance()
    rois = roiManager.getRoisAsArray()
    if not rois:
        print("No ROIs found.")
        return None
    largest_roi = max(rois, key=lambda r: r.getBounds().width * r.getBounds().height)
    return largest_roi

# Function to apply the determined ROI to each slice and measure it
def apply_roi_and_measure(imp, roi):
    stack = imp.getStack()
    measurements = []
    roiManager = RoiManager.getInstance()
    roiManager.addRoi(roi)

    for i in range(1, stack.getSize() + 1):
        imp.setSlice(i)
        imp.setRoi(roi)
        IJ.run(imp, "Measure", "")
        rt = ResultsTable.getResultsTable()
        if rt.getCounter() == 0:
            print("No measurements found for slice", i)
            continue

        area = rt.getValue("Area", rt.getCounter() - 1)
        min_gray = rt.getValue("Min", rt.getCounter() - 1)
        max_gray = rt.getValue("Max", rt.getCounter() - 1)
        integrated_density = rt.getValue("IntDen", rt.getCounter() - 1)
        mean_gray = rt.getValue("Mean", rt.getCounter() - 1)
        raw_integrated_density = rt.getValue("RawIntDen", rt.getCounter() - 1)
        stack_position = i

        measurements.append((area, min_gray, max_gray, integrated_density, mean_gray, raw_integrated_density, stack_position))
    
    roiManager.reset()
    return measurements

# Function to save the measurements to a CSV file
def save_measurements_to_csv(measurements, output_dir, file_name):
    output_path = os.path.join(output_dir, file_name + "_measurements.csv")
    with open(output_path, 'wb') as file:  # Use 'wb' for Python 2.x compatibility
        writer = csv.writer(file)
        if measurements:
            headers = ["Area", "Min", "Max", "IntDen", "Mean", "RawIntDen", "Stack Position"]
            writer.writerow(headers)
            for measurement in measurements:
                writer.writerow(measurement)

# Function to save the processed image
def save_processed_image(imp, srcDir, dstDir, currentDir, fileName):
    saveDir = currentDir.replace(srcDir, dstDir) if keepDirectories else dstDir
    if not os.path.exists(saveDir):
        os.makedirs(saveDir)
    savePath = os.path.join(saveDir, "Processed_" + fileName)
    print("Saving processed image to: " + savePath)
    try:
        IJ.saveAs(imp, "Tiff", savePath)
        print("Image saved successfully.")
    except Exception as e:
        print("Error saving image: " + str(e))
    imp.close()

# Run the script
run()
